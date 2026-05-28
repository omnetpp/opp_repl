"""
Synchronous MCP client for talking to a running OMNeT++ simulation that
exposes the Qtenv MCP server (``--mcp-server-address`` CLI flag).

The OMNeT++ MCP server is a plain HTTP+JSON-RPC endpoint at ``/mcp``.
We don't need SSE long-polling for our use case (every call is
client-initiated, the response comes back synchronously), so this
client speaks JSON-RPC over HTTP directly via ``httpx``.  That keeps
the threading and lifecycle model simple — no asyncio loops, no
anyio task groups, no cancellation surprises.
"""

import base64
import json
import logging

import httpx

__sphinx_mock__ = True

_logger = logging.getLogger(__name__)


class MCPError(RuntimeError):
    pass


class QtenvMCPClient:
    """Synchronous JSON-RPC client for a running Qtenv MCP server.

    Usage::

        client = QtenvMCPClient("http://127.0.0.1:8765/mcp")
        client.open()
        try:
            topology = client.get_network_topology()
            png_bytes = client.get_canvas_image("<root>")
        finally:
            client.close()
    """

    PROTOCOL_VERSION = "2025-06-18"

    def __init__(self, url, request_timeout=30.0):
        self.url = url
        self.request_timeout = request_timeout
        self._client = None
        self._session_id = None
        self._next_id = 1

    def open(self):
        if self._client is not None:
            raise RuntimeError("QtenvMCPClient is already open")
        self._client = httpx.Client(timeout=self.request_timeout)
        try:
            result = self._jsonrpc("initialize", {
                "protocolVersion": self.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "opp_repl", "version": "0"},
            }, capture_session=True)
            # MCP spec: after initialize, send an "initialized" notification.
            self._jsonrpc_notification("notifications/initialized", {})
            return result
        except Exception:
            self.close()
            raise

    def close(self):
        if self._client is None:
            return
        try:
            if self._session_id is not None:
                try:
                    self._client.delete(
                        self.url,
                        headers={"Mcp-Session-Id": self._session_id},
                        timeout=5.0,
                    )
                except Exception as e:
                    _logger.debug(f"MCP session terminate failed: {e}")
        finally:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            self._session_id = None

    def _headers(self):
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id is not None:
            h["Mcp-Session-Id"] = self._session_id
        return h

    def _jsonrpc(self, method, params=None, capture_session=False):
        req_id = self._next_id
        self._next_id += 1
        body = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        resp = self._client.post(self.url, headers=self._headers(), json=body)
        if capture_session:
            sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
            if sid:
                self._session_id = sid
        if resp.status_code >= 400:
            raise MCPError(f"HTTP {resp.status_code} from {self.url}: {resp.text[:200]}")
        return _parse_mcp_response(resp)

    def _jsonrpc_notification(self, method, params=None):
        body = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }
        # Notifications don't have an id; the server replies 202 with no body.
        resp = self._client.post(self.url, headers=self._headers(), json=body)
        if resp.status_code >= 400:
            raise MCPError(f"HTTP {resp.status_code} from {self.url}: {resp.text[:200]}")

    def list_tools(self):
        result = self._jsonrpc("tools/list", {})
        return [t["name"] for t in (result.get("tools") or [])]

    def call_tool(self, name, arguments=None):
        return self._jsonrpc("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })

    def get_simulation_state(self):
        result = self.call_tool("get_simulation_state", {})
        return _parse_text_content(result)

    def get_network_topology(self, max_depth=100):
        result = self.call_tool("get_network_topology", {"max_depth": max_depth})
        return _parse_text_content(result)

    def get_canvas_image(self, module_path, area="all_elements", margin=5):
        result = self.call_tool("get_canvas_image", {
            "module_path": module_path,
            "area": area,
            "margin": margin,
        })
        if result.get("isError"):
            raise MCPError(_error_text(result))
        for block in result.get("content") or []:
            block_type = block.get("type")
            data = block.get("data")
            mime = block.get("mimeType", "")
            if data and (block_type == "image" or mime.startswith("image/")):
                return base64.b64decode(data)
        raise MCPError("get_canvas_image returned no image content")

    def request_stop_simulation(self):
        try:
            self.call_tool("request_stop_simulation", {})
        except Exception as e:
            _logger.debug(f"request_stop_simulation failed (ignored): {e}")


def _parse_mcp_response(resp):
    """Parse a JSON-RPC response that may be JSON or SSE-framed JSON."""
    ctype = (resp.headers.get("content-type") or "").lower()
    text = resp.text
    if "text/event-stream" in ctype:
        # SSE — concatenate all "data:" lines for the first message.
        payload = ""
        for line in text.splitlines():
            if line.startswith("data:"):
                payload += line[len("data:"):].lstrip()
            elif not line.strip() and payload:
                break
        data = json.loads(payload) if payload else {}
    else:
        data = resp.json() if text else {}
    if "error" in data:
        err = data["error"]
        raise MCPError(f"MCP error {err.get('code')}: {err.get('message')}")
    return data.get("result", {})


def _parse_text_content(call_tool_result):
    if call_tool_result.get("isError"):
        raise MCPError(_error_text(call_tool_result))
    for block in call_tool_result.get("content") or []:
        text = block.get("text")
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return None


def _error_text(call_tool_result):
    pieces = []
    for block in call_tool_result.get("content") or []:
        text = block.get("text")
        if text:
            pieces.append(text)
    return "; ".join(pieces) or "MCP tool call failed"


def wait_for_mcp_ready(url, total_timeout=30.0, poll_interval=0.5):
    """Poll a candidate MCP endpoint until ``list_tools`` succeeds.

    Returns an open :class:`QtenvMCPClient` instance on success.  Raises
    :class:`TimeoutError` if the endpoint does not become ready within
    ``total_timeout`` seconds.
    """
    import time
    deadline = time.monotonic() + total_timeout
    last_error = None
    while time.monotonic() < deadline:
        per_attempt_timeout = min(5.0, max(1.0, deadline - time.monotonic()))
        client = QtenvMCPClient(url, request_timeout=per_attempt_timeout)
        try:
            client.open()
            client.list_tools()
            return client
        except Exception as e:
            last_error = e
            try:
                client.close()
            except Exception:
                pass
            time.sleep(poll_interval)
    raise TimeoutError(
        f"MCP endpoint {url} did not become ready within {total_timeout}s"
        + (f": {last_error}" if last_error else "")
    )
