# MCP Server

opp_repl can expose an **MCP (Model Context Protocol) server** that
allows AI assistants to execute Python code in the live REPL session.
Start it with `--mcp-port 9966` (disabled by default).

- **Transport**: Streamable HTTP (stateless)
- **Endpoint**: `http://127.0.0.1:{port}/mcp`
- Requires the `mcp` extra: `pip install -e ".[mcp]"`

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
| `file:///opp_repl/guides` | List available guide topics with one-line summaries |
| `file:///opp_repl/guide/{topic}` | Read a specific guide topic (e.g. `fingerprint_tests`, `concepts`) |

### API documentation resources

| URI | Description |
|---|---|
| `file:///opp_repl/packages` | List all opp_repl sub-packages with their docstrings |
| `file:///opp_repl/doc/package/{package_name}` | Compact API summary for a package — lists classes (with method names) and functions (with signatures) |
| `file:///opp_repl/doc/class/{class_name}` | Class docstring and public method signatures (without method docstrings) |
| `file:///opp_repl/doc/method/{class_name}/{method_name}` | Full documentation for a specific method |
| `file:///opp_repl/doc/function/{function_name}` | Full documentation for a specific function |

Class and function names can be fully qualified (e.g.
`opp_repl.simulation.workspace.SimulationWorkspace`) or short public
names (e.g. `SimulationWorkspace`).

### Recommended discovery flow

1. Read `file:///opp_repl/guides` to find the relevant guide topic
2. Read `file:///opp_repl/guide/{topic}` for usage examples
3. Read `file:///opp_repl/packages` to find the relevant sub-package
4. Read `file:///opp_repl/doc/package/{package_name}` for a compact API overview
5. Drill into `file:///opp_repl/doc/class/…`, `file:///opp_repl/doc/method/…`, or `file:///opp_repl/doc/function/…` for full details
