# MCP Server

opp_repl can expose an **MCP (Model Context Protocol) server** that
allows AI assistants to execute Python code in the live REPL session.
Start it with `--mcp-port 9966` (disabled by default).

- **Transport**: Streamable HTTP (stateless), endpoint `http://127.0.0.1:{port}/mcp`
- **Tool**: `execute_python` — runs arbitrary Python code in the IPython session
- **Resources**: guide topics, package listings, class/method/function documentation

Requires the `mcp` extra: `pip install -e ".[mcp]"`.
