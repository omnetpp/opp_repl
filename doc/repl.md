# The REPL

opp_repl is built around an **IPython shell** that has all simulation
functions pre-loaded.  This page describes REPL-specific features that go
beyond the standard IPython experience.

## Launching

```bash
opp_repl --load ~/workspace/omnetpp/omnetpp.opp \
         --load ~/workspace/inet/inet.opp
```

Key command-line options:

- `--load OPP_FILE` — load `.opp` descriptor file(s); accepts single
  files, directories (loads all `*.opp` inside), glob patterns, or the
  special token `@opp` for the bundled files.  Can be repeated.
- `-p PROJECT` — set the default simulation project by name.
- `--mcp-port PORT` — start an MCP server on the given TCP port for AI
  assistant integration (0 to disable).
- `-l LEVEL` — log level (`ERROR`, `WARN`, `INFO`, `DEBUG`).
- `--external-command-log-level LEVEL` — log level for output from
  simulations and build tools.
- `--no-handle-exception` — show full Python tracebacks instead of
  short error messages.

## Pre-loaded namespace

When the REPL starts, every public function from `opp_repl` is imported
into the top-level namespace — `run_simulations`, `build_project`,
`run_fingerprint_tests`, etc. — so you can call them without any prefix.

## Convenience variables

Every loaded simulation project is injected as a variable named
`{name}_project` (hyphens and dots become underscores).  For example,
loading `inet.opp` creates `inet_project`, and loading `simu5g.opp`
creates `simu5g_project`.  Use `get_simulation_project_variable_names()`
to list them all.

## Autoreload

IPython's `%autoreload 2` is enabled at startup.  If you edit Python source
files (e.g. a user module or opp_repl itself), changes are picked up
automatically before each command — no need to restart the REPL.

## User module

At startup the REPL tries to import a Python module named after the current
OS login user (e.g. `import levy`).  All public names from that module are
injected into the namespace.  This lets you define personal helper functions,
set project defaults, or customize the environment without modifying
opp_repl itself.  If no such module exists, the import is silently skipped.

## Stopping execution

Call `stop_execution()` (or `stop_execution(value)`) anywhere in a REPL
script to abort the current cell cleanly, without a full traceback.  This
is useful in multi-line REPL scripts where you want to bail out early.

## MCP server

When started with `--mcp-port`, the REPL exposes its functions to AI
assistants via the Model Context Protocol.  See [MCP server](mcp_server.md)
for details.
