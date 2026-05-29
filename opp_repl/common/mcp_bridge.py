"""
Stdio to Unix-domain-socket bridge for the opp_repl MCP server.

Connects the MCP stdio transport (used by AI coding tools like Windsurf,
Claude Code, VS Code, and Cursor) to the opp_repl MCP server listening on a
Unix domain socket (started with ``opp_repl --mcp-socket``).

Each line read from stdin is a JSON-RPC message that is forwarded as an HTTP
POST to the MCP server over the socket.  Responses (JSON or SSE-streamed
frames) are written back to stdout as newline-terminated JSON objects.
"""

import argparse
import json
import os
import socket as _socket
import sys
import textwrap
import threading
import time

__sphinx_mock__ = True


def _default_socket_path():
    """Return the default per-user Unix socket path (read-only, no side effects)."""
    xdg = os.environ.get("XDG_RUNTIME_DIR", "")
    if xdg and os.path.isdir(xdg):
        base = os.path.join(xdg, "opp_repl")
    else:
        base = os.path.join("/tmp", f"opp_repl-{os.getuid()}")
    return os.path.join(base, "mcp.sock")


def _build_epilog(sock):
    # Show the simpler no-args form first since that's the recommended config
    return textwrap.dedent(f"""\
------------------------------------------------------------------------
Default socket path for this user:
  {sock}

NOTE: --mcp-socket can be omitted entirely when the opp_repl server uses
      the default path (which is the case when launched with --mcp-socket
      without an explicit PATH argument).

------------------------------------------------------------------------
CLIENT CONFIGURATION EXAMPLES
------------------------------------------------------------------------

Windsurf  (~/.codeium/windsurf/mcp_config.json)
  Simple form (default socket path -- no args needed):
    {{
      "mcpServers": {{
        "opp_repl": {{
          "command": "opp_repl_mcp_bridge"
        }}
      }}
    }}

  Explicit path (use when opp_repl was started with a custom --mcp-socket):
    {{
      "mcpServers": {{
        "opp_repl": {{
          "command": "opp_repl_mcp_bridge",
          "args": ["--mcp-socket", "{sock}"]
        }}
      }}
    }}

------------------------------------------------------------------------

Claude Code
  Install from the command line (recommended):
    claude mcp add --transport stdio opp_repl -- opp_repl_mcp_bridge

  Explicit socket path (when opp_repl was started with a custom --mcp-socket):
    claude mcp add --transport stdio opp_repl -- opp_repl_mcp_bridge --mcp-socket {sock}

  Or by editing ~/.claude.json (user scope) or .mcp.json (project scope):
    {{
      "mcpServers": {{
        "opp_repl": {{
          "type": "stdio",
          "command": "opp_repl_mcp_bridge"
        }}
      }}
    }}

------------------------------------------------------------------------

VS Code / Cursor  (.vscode/mcp.json  or  settings.json "mcp.servers")
  Install from the command line (VS Code only):
    code --add-mcp '{{"name":"opp_repl","type":"stdio","command":"opp_repl_mcp_bridge"}}'

  Or by editing the config file -- simple form:
    {{
      "servers": {{
        "opp_repl": {{
          "type": "stdio",
          "command": "opp_repl_mcp_bridge"
        }}
      }}
    }}

  Explicit path:
    {{
      "servers": {{
        "opp_repl": {{
          "type": "stdio",
          "command": "opp_repl_mcp_bridge",
          "args": ["--mcp-socket", "{sock}"]
        }}
      }}
    }}

------------------------------------------------------------------------
Start the opp_repl MCP server:
  opp_repl --mcp-socket          # uses the default path above
  opp_repl --mcp-socket PATH     # uses an explicit path
------------------------------------------------------------------------
""")


def _emit_json(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _emit_error(req_id, code, message):
    _emit_json({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    })


def _probe_socket(socket_path):
    """Return True if a process is listening on *socket_path*."""
    if not os.path.exists(socket_path):
        return False
    probe = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    try:
        probe.connect(socket_path)
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _emit_notification(level, message):
    """Emit an MCP notifications/message log notification to the client."""
    _emit_json({
        "jsonrpc": "2.0",
        "method": "notifications/message",
        "params": {
            "level": level,
            "logger": "opp_repl_mcp_bridge",
            "data": message,
        },
    })


def _make_error_result(req_id, message):
    """Return a MCP tool-result JSON-RPC response with isError=true."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "content": [{"type": "text", "text": message}],
            "isError": True,
        },
    }


# Shared state for the connection monitor
_connected = False
_state_lock = threading.Lock()


def _connection_monitor(socket_path, interval=2.0):
    """Background thread: poll socket every *interval* seconds, emit notifications on state change.

    Initial state is announced by _proxy synchronously after the client's first
    message arrives (MCP forbids pre-handshake server->client notifications);
    this monitor only handles subsequent state-change notifications.
    """
    global _connected
    while True:
        time.sleep(interval)
        reachable = _probe_socket(socket_path)
        with _state_lock:
            was_connected = _connected
            _connected = reachable
        if reachable and not was_connected:
            _emit_notification("info", f"opp_repl MCP server is now reachable at {socket_path}")
        elif not reachable and was_connected:
            _emit_notification("error", f"opp_repl MCP server is no longer reachable at {socket_path}. Start opp_repl with --mcp-socket.")


def _proxy(socket_path):
    try:
        import httpx
    except ImportError:
        sys.stderr.write(
            "opp_repl_mcp requires httpx. Install it with: pip install opp_repl[mcp]\n"
        )
        sys.exit(1)

    # Seed initial state before launching the monitor so its first poll
    # compares against reality, not the default False.
    global _connected
    with _state_lock:
        _connected = _probe_socket(socket_path)

    threading.Thread(
        target=_connection_monitor, args=(socket_path,), daemon=True, name="opp-repl-mcp-monitor"
    ).start()

    transport = httpx.HTTPTransport(uds=socket_path)
    session_id = None
    announced_initial_state = False

    with httpx.Client(transport=transport, base_url="http://localhost", timeout=300.0) as client:
        for raw in sys.stdin.buffer:
            line = raw.decode("utf-8", errors="replace").rstrip("\n\r")
            if not line:
                continue

            # Announce initial reachability on the first client message: MCP
            # forbids server->client notifications before the handshake begins,
            # so we cannot emit eagerly from the monitor thread.
            if not announced_initial_state:
                announced_initial_state = True
                with _state_lock:
                    initial_connected = _connected
                if initial_connected:
                    _emit_notification("info", f"opp_repl MCP server is reachable at {socket_path}")
                else:
                    _emit_notification("error", f"opp_repl MCP server is not reachable at {socket_path}. Start opp_repl with --mcp-socket.")

            try:
                msg = json.loads(line)
            except json.JSONDecodeError as exc:
                _emit_error(None, -32700, f"Parse error: {exc}")
                continue

            req_id = msg.get("id")
            is_notification = "id" not in msg
            method = msg.get("method", "")
            is_tool_call = method == "tools/call"

            with _state_lock:
                connected = _connected

            if not connected and not is_notification:
                # Fast path: known disconnected — immediately return proper error
                if is_tool_call:
                    _emit_json(_make_error_result(
                        req_id,
                        f"opp_repl is not running or its MCP socket is unavailable ({socket_path}). "
                        f"Start opp_repl with --mcp-socket and retry.",
                    ))
                else:
                    _emit_error(req_id, -32000, f"Connection refused: {socket_path}")
                continue

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Host": "localhost",
            }
            if session_id:
                headers["Mcp-Session-Id"] = session_id

            try:
                with client.stream(
                    "POST", "/mcp",
                    content=line.encode("utf-8"),
                    headers=headers,
                ) as resp:
                    new_sid = (
                        resp.headers.get("mcp-session-id")
                        or resp.headers.get("Mcp-Session-Id")
                    )
                    if new_sid:
                        session_id = new_sid

                    if resp.status_code == 202:
                        continue

                    if resp.status_code >= 400:
                        if not is_notification:
                            body = resp.read().decode("utf-8", errors="replace").strip()
                            _emit_error(req_id, resp.status_code, f"HTTP {resp.status_code}: {body[:200]}")
                        continue

                    content_type = resp.headers.get("content-type", "")
                    if "text/event-stream" in content_type:
                        for sse_line in resp.iter_lines():
                            if sse_line.startswith("data:"):
                                data = sse_line[5:].strip()
                                if data and data != "[DONE]":
                                    sys.stdout.write(data + "\n")
                                    sys.stdout.flush()
                    else:
                        body = resp.read().decode("utf-8", errors="replace").strip()
                        if body:
                            sys.stdout.write(body + "\n")
                            sys.stdout.flush()

            except httpx.ConnectError as exc:
                session_id = None
                sys.stderr.write(
                    f"Cannot connect to opp_repl MCP server at {socket_path}: {exc}\n"
                    f"Make sure opp_repl is running with --mcp-socket.\n"
                )
                sys.stderr.flush()
                if not is_notification:
                    if is_tool_call:
                        _emit_json(_make_error_result(
                            req_id,
                            f"opp_repl is not running or its MCP socket is unavailable ({socket_path}). "
                            f"Start opp_repl with --mcp-socket and retry.",
                        ))
                    else:
                        _emit_error(req_id, -32000, f"Connection refused: {socket_path}")
            except Exception as exc:
                if not is_notification:
                    _emit_error(req_id, -32000, str(exc))


def main():
    default_sock = _default_socket_path()

    parser = argparse.ArgumentParser(
        prog="opp_repl_mcp",
        description=(
            "Stdio to Unix-domain-socket bridge for the opp_repl MCP server.\n\n"
            "Forwards MCP stdio messages (from an AI coding assistant) to an\n"
            "opp_repl process listening on a Unix domain socket."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_build_epilog(default_sock),
    )
    parser.add_argument(
        "--mcp-socket",
        default=None,
        metavar="PATH",
        help=(
            f"path to the Unix domain socket created by opp_repl --mcp-socket "
            f"(default: {default_sock}); "
            f"omit this argument when using the default socket path"
        ),
    )
    args = parser.parse_args()

    socket_path = args.mcp_socket if args.mcp_socket is not None else default_sock
    _proxy(socket_path)


if __name__ == "__main__":
    main()
