#!/usr/bin/env python3
"""
Integration tests for the Unix domain socket MCP server and the stdio bridge
(opp_repl_mcp_bridge).

Tests the full communication stack:

    opp_repl_mcp_bridge (stdio bridge) --> UDS socket --> opp_repl MCP server

Each test case starts a fresh in-process UDS server on a temp socket path, then
drives the bridge as a subprocess with pre-built JSON-RPC input.
"""

import json
import os
import socket as _socket
import subprocess
import sys
import tempfile
import time
import unittest

__sphinx_mock__ = True  # ignore this module in documentation

# Module-level server state: started once in setUpModule, shared by all tests.
_server_tmpdir = None
_server_sock = None


def setUpModule():
    """Start the UDS MCP server once for the entire test module.

    The module-level FastMCP singleton (_mcp in mcp.py) creates its
    StreamableHTTPSessionManager lazily and can only run one uvicorn server
    per process, so all tests share this single instance.
    """
    global _server_tmpdir, _server_sock
    _server_tmpdir = tempfile.TemporaryDirectory(prefix="opp_repl_mcp_bridge_test_")
    _server_sock = os.path.join(_server_tmpdir.name, "mcp.sock")
    _start_uds_server(_server_sock)


def tearDownModule():
    global _server_tmpdir
    if _server_tmpdir is not None:
        _server_tmpdir.cleanup()
        _server_tmpdir = None


def _wait_for_socket(path, timeout=10.0):
    """Block until the UDS socket file exists and accepts a connection."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            probe = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            try:
                probe.connect(path)
                return True
            except OSError:
                pass
            finally:
                probe.close()
        time.sleep(0.05)
    return False


def _start_uds_server(socket_path):
    """Start the MCP UDS server in-process; return the background thread."""
    from opp_repl.common.mcp import start_mcp_server
    thread = start_mcp_server(socket_path=socket_path)
    if not _wait_for_socket(socket_path):
        raise RuntimeError(f"MCP UDS server did not start at {socket_path}")
    return thread


def _run_bridge(socket_path, messages, timeout=15):
    """
    Spawn opp_repl_mcp_bridge pointing at *socket_path*, pipe *messages* (a list of
    JSON-serialisable dicts) to its stdin, and return (responses, stderr_text).

    *responses* is a list of parsed JSON objects (lines that were written to
    the bridge's stdout).
    """
    stdin_data = "".join(json.dumps(m) + "\n" for m in messages).encode()
    result = subprocess.run(
        [sys.executable, "-c",
         "from opp_repl.common.mcp_bridge import main; main()",
         "--mcp-socket", socket_path],
        input=stdin_data,
        capture_output=True,
        timeout=timeout,
    )
    responses = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.decode("utf-8", errors="replace").strip()
        if line:
            try:
                responses.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return responses, result.stderr.decode("utf-8", errors="replace"), result.returncode


# ─────────────────────────────────────────────────────────────────────────────
# Direct UDS server tests (httpx, no bridge subprocess)
# ─────────────────────────────────────────────────────────────────────────────

def _httpx_post_mcp(sock, msg, timeout=10):
    """POST a single JSON-RPC *msg* to the UDS MCP server.

    Handles both plain-JSON and SSE (text/event-stream) response bodies.
    Returns the first parsed JSON object found in the response, or None for
    202 Accepted (notifications).
    """
    import httpx
    transport = httpx.HTTPTransport(uds=sock)
    with httpx.Client(transport=transport, base_url="http://localhost", timeout=timeout) as client:
        with client.stream(
            "POST", "/mcp",
            content=json.dumps(msg).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        ) as resp:
            if resp.status_code == 202:
                return None, resp.status_code
            content_type = resp.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                for line in resp.iter_lines():
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data and data != "[DONE]":
                            return json.loads(data), resp.status_code
            else:
                body = resp.read().decode("utf-8", errors="replace").strip()
                if body:
                    return json.loads(body), resp.status_code
    return None, resp.status_code


class TestUdsServerDirect(unittest.TestCase):
    """Connect to the UDS server directly via httpx, bypassing the bridge."""

    def test_initialize_via_httpx(self):
        msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.1.0"},
            },
        }
        data, status = _httpx_post_mcp(_server_sock, msg)
        self.assertIn(status, (200, 201, 202),
                      f"Unexpected HTTP status: {status}")
        if data is not None:
            self.assertEqual(data.get("id"), 1)
            self.assertNotIn("error", data,
                             f"initialize returned an error: {data}")
            self.assertIn("result", data)
            self.assertIn("protocolVersion", data["result"])

    def test_tools_list_via_httpx(self):
        msg = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }
        data, status = _httpx_post_mcp(_server_sock, msg)
        self.assertIn(status, (200, 201, 202),
                      f"Unexpected HTTP status: {status}")
        if data is not None:
            self.assertNotIn("error", data,
                             f"tools/list returned an error: {data}")
            self.assertIn("result", data)
            tool_names = [t["name"] for t in data["result"].get("tools", [])]
            self.assertIn("execute_python", tool_names,
                          f"execute_python not found; tools: {tool_names}")

    def test_socket_permissions(self):
        """Socket file must be owner-only (mode 0o600)."""
        mode = oct(os.stat(_server_sock).st_mode & 0o777)
        self.assertEqual(mode, oct(0o600),
                         f"Socket has wrong permissions: {mode}")


# ─────────────────────────────────────────────────────────────────────────────
# Bridge (stdio ↔ UDS) integration tests
# ─────────────────────────────────────────────────────────────────────────────

class TestMcpBridge(unittest.TestCase):
    """End-to-end tests through the opp_repl_mcp_bridge stdio bridge."""

    def test_initialize_and_tools_list(self):
        """Bridge must forward initialize + tools/list and return valid responses."""
        messages = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0.1.0"},
                },
            },
            # notifications/initialized has no id → no response expected
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        ]

        responses, stderr_text, returncode = _run_bridge(_server_sock, messages)
        by_id = {r["id"]: r for r in responses if "id" in r}

        # --- initialize response ---
        self.assertIn(1, by_id,
                      f"No initialize response (id=1).\nstderr:\n{stderr_text}")
        init_resp = by_id[1]
        self.assertNotIn("error", init_resp,
                         f"initialize returned error: {init_resp}")
        self.assertIn("result", init_resp)
        self.assertIn("protocolVersion", init_resp["result"])

        # --- tools/list response ---
        self.assertIn(2, by_id,
                      f"No tools/list response (id=2).\nstderr:\n{stderr_text}")
        tools_resp = by_id[2]
        self.assertNotIn("error", tools_resp,
                         f"tools/list returned error: {tools_resp}")
        self.assertIn("result", tools_resp)
        tool_names = [t["name"] for t in tools_resp["result"].get("tools", [])]
        self.assertIn("execute_python", tool_names,
                      f"execute_python not found; tools: {tool_names}")

    def test_bridge_connection_error(self):
        """Bridge must return isError=true and emit a notification when the socket is missing."""
        with tempfile.TemporaryDirectory(prefix="opp_repl_mcp_bridge_err_") as tmpdir:
            missing_sock = os.path.join(tmpdir, "nonexistent.sock")

            init_msg = [
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0.1.0"},
                    },
                },
            ]

            responses, stderr_text, returncode = _run_bridge(missing_sock, init_msg)

            # Bridge should stay alive (returncode 0) and return an error result
            self.assertEqual(returncode, 0,
                f"Expected bridge to stay alive (exit 0), got {returncode}.\n"
                f"stderr: {stderr_text}")
            # Should have an error notification (no id, method=notifications/message)
            notifications = [r for r in responses if r.get("method") == "notifications/message"]
            self.assertTrue(len(notifications) > 0,
                f"Expected at least one notifications/message. responses={responses}")
            self.assertEqual(notifications[0]["params"]["level"], "error")
            # initialize is not a tool call — it should get a JSON-RPC error
            init_responses = [r for r in responses if r.get("id") == 1]
            self.assertTrue(len(init_responses) > 0,
                f"Expected initialize response (id=1). responses={responses}")
            self.assertIn("error", init_responses[0],
                f"Expected JSON-RPC error for initialize. response={init_responses[0]}")

    def test_bridge_survives_when_no_server(self):
        """Bridge must exit cleanly when no server is listening and no client messages arrive.

        With empty stdin the client never starts the MCP handshake, so the bridge
        must emit no server->client notifications (MCP forbids pre-init notifications)
        and exit 0 as soon as stdin closes.
        """
        with tempfile.TemporaryDirectory(prefix="opp_repl_mcp_bridge_nosrv_") as tmpdir:
            missing_sock = os.path.join(tmpdir, "nonexistent.sock")
            result = subprocess.run(
                [sys.executable, "-c",
                 "from opp_repl.common.mcp_bridge import main; main()",
                 "--mcp-socket", missing_sock],
                input=b"",
                capture_output=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0,
                             f"Expected bridge to stay alive (exit 0), got {result.returncode}.\n"
                             f"stderr: {result.stderr.decode()}")
            stdout_lines = [json.loads(l) for l in result.stdout.decode().strip().splitlines() if l.strip()]
            self.assertEqual(stdout_lines, [],
                f"Expected no JSON-RPC output when the client never speaks; got {stdout_lines}")

    def test_bridge_survives_server_crash(self):
        """Bridge must stay alive when the server disappears mid-session, emitting notifications."""
        import threading

        with tempfile.TemporaryDirectory(prefix="opp_repl_mcp_bridge_crash_") as tmpdir:
            sock_path = os.path.join(tmpdir, "mcp.sock")

            # Start a dummy listener that accepts (and discards) connections
            # so the bridge's startup probe succeeds.
            listener = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            listener.bind(sock_path)
            listener.listen(5)
            stop_accept = threading.Event()

            def _accept_loop():
                listener.settimeout(0.2)
                while not stop_accept.is_set():
                    try:
                        conn, _ = listener.accept()
                        conn.close()
                    except _socket.timeout:
                        pass
                    except OSError:
                        break

            accept_thread = threading.Thread(target=_accept_loop, daemon=True)
            accept_thread.start()

            # Launch bridge with a blocking stdin (won't close immediately)
            proc = subprocess.Popen(
                [sys.executable, "-c",
                 "from opp_repl.common.mcp_bridge import main; main()",
                 "--mcp-socket", sock_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Give the bridge time to import and reach the proxy loop
            time.sleep(2.0)
            self.assertIsNone(proc.poll(), "Bridge exited prematurely")

            # Simulate server crash: stop accepting, close and remove the socket
            stop_accept.set()
            accept_thread.join(timeout=2)
            listener.close()
            os.unlink(sock_path)

            # The monitor polls every 2s, allow time for detection
            time.sleep(5.0)
            self.assertIsNone(proc.poll(), "Bridge exited after server crash")

            proc.stdin.close()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

            self.assertEqual(proc.returncode, 0,
                             f"Expected exit 0 after stdin close, got {proc.returncode}")
            # Notifications are JSON-RPC messages on stdout
            stdout_text = proc.stdout.read().decode()
            stdout_lines = [json.loads(l) for l in stdout_text.strip().splitlines() if l.strip()]
            notifications = [r for r in stdout_lines if r.get("method") == "notifications/message"]
            self.assertTrue(len(notifications) > 0,
                f"Expected at least one notification. stdout={stdout_lines}")
            self.assertIn("no longer reachable", notifications[-1]["params"]["data"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
