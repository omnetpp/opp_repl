# OMNeT++ Projects

An `OmnetppProject` represents a specific **OMNeT++ installation** on disk.
It knows where to find executables like `opp_run`, how to set up the
environment, and how to build OMNeT++ itself.

## How it is defined

An OMNeT++ project is typically defined in a `.opp` file:

```python
OmnetppProject(
    environment_variable="__omnetpp_root_dir",
    root_folder="/home/user/workspace/omnetpp",
)
```

The `root_folder` takes precedence; if omitted, the path is resolved from
the `environment_variable`.

## What it provides

- **Executable resolution** — `get_executable(mode="release")` returns the
  full path to `opp_run_release`, `opp_run_dbg`, etc.
- **Environment setup** — `get_env()` returns an environment dict with the
  OMNeT++ `bin/` and `lib/` directories on `PATH` and `LD_LIBRARY_PATH`.
- **Building** — `build(mode="release")` runs `make` in the OMNeT++ root
  with the appropriate mode.  If a `Makefile.inc` is missing (e.g. in a
  fresh git worktree), `ensure_configured()` runs `./configure` first.
- **Cleaning** — `clean(mode="release")` runs `make clean`.

## Build modes

The mode determines which binary suffix is used:

| Mode | Suffix |
|---|---|
| `release` | `_release` |
| `debug` | `_dbg` |
| `sanitize` | `_sanitize` |
| `coverage` | `_coverage` |
| `profile` | `_profile` |

## Overlay builds

When `overlay_key` is specified, the project uses an overlay filesystem
(via fuse-overlayfs) so that builds happen in a separate layer on top of
the original source tree.  This is useful for testing patches without
modifying the installation.  See [overlay_builds.md](overlay_builds.md).

## opp_env integration

For OMNeT++ installations managed by the `opp_env` tool, set
`opp_env_workspace` and `opp_env_project`.  Build and run commands will
then be routed through `opp_env run` automatically.

## The default OMNeT++ project

There is a global default OMNeT++ project, set automatically when the
default simulation project is determined.  If the simulation project
references a specific `OmnetppProject`, that one is used; otherwise the
project registered under the name `"omnetpp"` is the fallback.

```python
get_default_omnetpp_project()
```
