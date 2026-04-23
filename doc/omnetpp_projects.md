# OMNeT++ Projects

An `OmnetppProject` represents a specific **OMNeT++ installation** on disk.
It knows where to find executables like `opp_run`, how to set up the
environment, and how to build OMNeT++ itself.

## How it is defined

An OMNeT++ project is typically defined in a `.opp` file.  Using an
environment variable:

```python
OmnetppProject(
    root_folder_environment_variable="__omnetpp_root_dir",
)
```

Using a relative path — `root_folder="."` refers to the directory containing
the `.opp` file:

```python
# ~/workspace/omnetpp/omnetpp.opp
OmnetppProject(
    name="omnetpp",
    root_folder=".",
)
```

Or using an absolute path — useful when the `.opp` file is stored
separately from the installation:

```python
OmnetppProject(
    root_folder="/home/user/workspace/omnetpp",
)
```

Projects can also be defined programmatically from the REPL or a Python
script using `define_omnetpp_project()`.  This is useful when the root
folder is computed at runtime — for example, when creating a git worktree
for a specific version:

```python
import subprocess

worktree = "/tmp/omnetpp-v6.1"
subprocess.run(["git", "worktree", "add", worktree, "v6.1"],
               cwd="/home/user/workspace/omnetpp")
define_omnetpp_project("omnetpp-6.1", root_folder=worktree)
```

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

When `overlay_name` is specified, the project uses an overlay filesystem
(via fuse-overlayfs) so that builds happen in a separate layer on top of
the original source tree.  This is useful for testing patches without
modifying the installation.  See [Overlay builds](overlay_builds.md).

The key addition here is `overlay_name` — all builds will happen in a
separate overlay layer, leaving the original source tree untouched:

```python
OmnetppProject(
    name="omnetpp-patched",
    root_folder=".",
    overlay_name="omnetpp-patched",
)
```

## opp_env integration

For OMNeT++ installations managed by the `opp_env` tool, set
`opp_env_workspace` and `opp_env_project`.  Build and run commands will
then be routed through `opp_env run` automatically.  The key additions
are `opp_env_workspace` (path to the opp_env installation) and
`opp_env_project` (the version identifier known to opp_env):

```python
OmnetppProject(
    name="omnetpp-6.3.0",
    root_folder=".",
    opp_env_workspace="/home/user/opp_env",
    opp_env_project="omnetpp-6.3.0",
)
```

## Automatic detection

When a simulation project references an OMNeT++ project by name (e.g.
`omnetpp_project="omnetpp"`) and no project with that name has been
registered, opp_repl automatically creates one from the
`__omnetpp_root_dir` environment variable.  This means you do not need to
write or load an `omnetpp.opp` file for the standard case — as long as
`__omnetpp_root_dir` is set (which is done by the OMNeT++ `setenv` script),
everything works out of the box:

```bash
cd ~/workspace/omnetpp/samples/aloha
opp_run_simulations --filter PureAloha -t 1s
```

If you need to customize the OMNeT++ project (e.g. overlay builds or
opp_env integration), define it explicitly via a `.opp` file or
`define_omnetpp_project()`.

## Looking up projects

At REPL startup, every loaded OMNeT++ project is injected as a convenience
variable `{name}_project` (hyphens and dots become underscores), e.g.
`omnetpp_project`.  Projects can also be looked up by name:

```python
omnetpp_project                # convenience variable
get_omnetpp_project("omnetpp") # look up by name
get_default_omnetpp_project()  # the current default
```

The default OMNeT++ project is set automatically when the default
simulation project is determined.  If that simulation project references a
specific `OmnetppProject`, that one becomes the default; otherwise the
project registered under the name `"omnetpp"` is used as fallback.
