# MCP Server

opp_repl can expose an **MCP (Model Context Protocol) server** that
allows AI assistants to execute Python code in the live REPL session.
Start it with `--mcp-port 9966` (disabled by default).

- **Transport**: Streamable HTTP (stateless)
- **Endpoint**: `http://127.0.0.1:{port}/mcp`
- **Authentication**: Bearer token (SHA-256 hash passed via `--mcp-token-hash`)
- Requires the `mcp` extra: `pip install -e ".[mcp]"`

## Authentication

The MCP server requires bearer token authentication.  The AI client
generates a random token, computes its SHA-256 hash, and passes the
**hash** on the command line.  The raw token never appears in process
arguments or shell history.

```bash
# Example: AI client generates a token, hashes it, and launches opp_repl
TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
HASH=$(echo -n "$TOKEN" | sha256sum | cut -d' ' -f1)
opp_repl --mcp-port 9966 --mcp-token-hash "$HASH"
```

The client then sends `Authorization: Bearer <TOKEN>` with every HTTP
request.  opp_repl hashes the incoming token and compares it to the
stored hash (timing-safe).  Requests without a valid token are rejected.

## Running inside opp_sandbox

When opp_repl is launched inside `opp_sandbox` (the bubblewrap-based
sandbox shipped with OMNeT++), the sandbox already provides
filesystem-level isolation: the process can only write to the working
directory and explicitly mounted paths, capabilities are dropped, and
namespaces are isolated.

In this case `--mcp-token-hash` can be omitted — opp_repl detects
the sandbox environment and starts the MCP server without
authentication:

```bash
opp_sandbox -w ~/workspace -- opp_repl --load "opp/*.opp" --mcp-port 9966
```

Use `-w` / `--writable` to grant the sandbox write access to
additional directories (e.g. `~/workspace`).  Use `-m` / `--mount` for
read-only mounts.

Sandbox detection works by checking for the `/.opp_sandbox` sentinel
file that `opp_sandbox` bind-mounts (read-only) into the container,
and verifying that the file is actually read-only.

## Tools

### `execute_python(code: str) -> str`

Execute Python code in the live IPython session.  The code runs in the
same namespace as the interactive REPL user — all public opp_repl
packages, functions and classes are pre-loaded.

Returns captured stdout/stderr output.  If the code is a single
expression, its repr is returned.

## Resources

### Guide resources

| URI | Description |
|---|---|
| `opp-repl://guides` | List available guide topics with first-paragraph summaries |
| `opp-repl://guide/{topic}` | Read a specific guide topic (e.g. `fingerprint_tests`, `concepts`) |

### API documentation resources

| URI | Description |
|---|---|
| `opp-repl://packages` | List all opp_repl sub-packages with first-paragraph summaries |
| `opp-repl://package/{package_name}` | Full package docstring, first paragraph per class, one-line summary per method, signature + one-line per function |
| `opp-repl://class/{class_name}` | Full class docstring, method signatures with first-paragraph summaries |
| `opp-repl://method/{class_name}/{method_name}` | Complete method documentation |
| `opp-repl://function/{function_name}` | Complete function documentation |

Class and function names can be fully qualified (e.g.
`opp_repl.simulation.workspace.SimulationWorkspace`) or short public
names (e.g. `SimulationWorkspace`).

### Recommended discovery flow

1. Read `opp-repl://guides` to find the relevant guide topic
2. Read `opp-repl://guide/{topic}` for usage examples
3. Read `opp-repl://packages` to find the relevant sub-package
4. Read `opp-repl://package/{package_name}` for a compact API overview
5. Drill into `opp-repl://class/…`, `opp-repl://method/…`, or `opp-repl://function/…` for full details

## Unix Domain Socket Transport (recommended for local use)

Start opp_repl with `--mcp-socket` to listen on a Unix domain socket
instead of a TCP port:

```bash
opp_repl --mcp-socket              # uses stable per-user default path
opp_repl --mcp-socket /custom/path # explicit path
```

The default socket path is `$XDG_RUNTIME_DIR/opp_repl/mcp.sock` (falling
back to `/tmp/opp_repl-<uid>/mcp.sock`).  The socket is created with
permissions `0600` (owner-only), so **no bearer token is required** — the
filesystem enforces access control.

`--mcp-socket` and `--mcp-port` are mutually exclusive.

### opp_repl_mcp_bridge bridge

Since most AI coding tools speak MCP over stdio rather than HTTP, a
small bridge command is provided:

```bash
opp_repl_mcp_bridge                     # connects to the default socket path
opp_repl_mcp_bridge --mcp-socket PATH   # connects to a custom path
```

Run `opp_repl_mcp_bridge --help` to see the resolved default path and
ready-to-paste configuration snippets for all supported clients.

### Client configuration (Unix socket)

The simplest config — **no arguments needed when using the default path**:

**Windsurf** (`~/.codeium/windsurf/mcp_config.json`):

```json
{
  "mcpServers": {
    "opp_repl": {
      "command": "opp_repl_mcp_bridge"
    }
  }
}
```

**Claude Code** (`~/.claude.json` or `.mcp.json` for project scope):

```json
{
  "mcpServers": {
    "opp_repl": {
      "type": "stdio",
      "command": "opp_repl_mcp_bridge"
    }
  }
}
```

Or via the `claude` CLI:

```bash
claude mcp add --transport stdio opp_repl -- opp_repl_mcp_bridge
```

**VS Code / Cursor** (`.vscode/mcp.json`):

```json
{
  "servers": {
    "opp_repl": {
      "type": "stdio",
      "command": "opp_repl_mcp_bridge"
    }
  }
}
```

## Client Configuration (TCP)

### Windsurf / Codeium

Add the following to your MCP configuration file
(`~/.codeium/windsurf/mcp_config.json`):

```json
{
  "mcpServers": {
    "opp_repl": {
      "disabled": false,
      "headers": {
        "Authorization": "Bearer <your_token>"
      },
      "url": "http://localhost:9966/mcp"
    }
  }
}
```

Replace `<your_token>` with the raw bearer token whose SHA-256 hash was
passed to `--mcp-token-hash` when launching opp_repl.  If running inside
`opp_sandbox` (no authentication), you can omit the `headers` field or
use any placeholder value.
