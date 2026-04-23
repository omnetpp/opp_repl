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
