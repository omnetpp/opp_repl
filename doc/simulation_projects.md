# Simulation Projects

A `SimulationProject` represents a **simulation model project** — a
codebase that contains NED modules, C++ sources, and example simulations.
Examples include INET, Simu5G, or any of the OMNeT++ sample projects.

## Defining a project

Projects are defined in `.opp` descriptor files (see
[OPP files](opp_files.md) for the full format).

Using a relative path — `root_folder="."` refers to the directory containing
the `.opp` file.  This is the recommended approach when the `.opp` file
lives inside the project tree:

```python
# ~/workspace/inet/inet.opp
SimulationProject(
    name="inet",
    root_folder=".",
    omnetpp_project="omnetpp",
    library_folder="src",
    bin_folder="bin",
    dynamic_libraries=["INET"],
    ned_folders=["src", "examples", "showcases", "tutorials"],
    ini_file_folders=["examples", "showcases", "tutorials"],
)
```

Using an environment variable — useful for shared `.opp` files that are not
stored inside the project tree:

```python
SimulationProject(
    name="inet",
    root_folder_environment_variable="INET_ROOT",
    library_folder="src",
    bin_folder="bin",
    dynamic_libraries=["INET"],
    ned_folders=["src", "examples", "showcases", "tutorials"],
    ini_file_folders=["examples", "showcases", "tutorials"],
)
```

Using an environment variable with a relative folder — for projects that
live as subdirectories under a common root (e.g. OMNeT++ samples):

```python
SimulationProject(
    name="aloha",
    root_folder_environment_variable="__omnetpp_root_dir",
    root_folder_environment_variable_relative_folder="samples/aloha",
    omnetpp_project="omnetpp",
    build_types=["executable"],
    ned_folders=["."],
    ini_file_folders=["."],
)
```

Using an absolute path — useful when the `.opp` file is not stored inside
the project tree:

```python
SimulationProject(
    name="inet",
    root_folder="/home/user/workspace/inet",
    omnetpp_project="omnetpp",
    ned_folders=["src", "examples", "showcases", "tutorials"],
    ini_file_folders=["examples", "showcases", "tutorials"],
)
```

Projects can also be defined programmatically from the REPL or a Python
script using `define_simulation_project()`.  This is useful when the root
folder is computed at runtime — for example, when creating a git worktree
for a specific version:

```python
import subprocess

worktree = "/tmp/inet-v4.5"
subprocess.run(["git", "worktree", "add", worktree, "v4.5"],
               cwd="/home/user/workspace/inet")
define_simulation_project("inet-4.5", root_folder=worktree,
                          omnetpp_project="omnetpp",
                          library_folder="src", bin_folder="bin",
                          dynamic_libraries=["INET"],
                          ned_folders=["src", "examples"],
                          ini_file_folders=["examples"])
```

## Source layout

A project tells opp_repl where everything lives through a set of folder
parameters, all relative to the root:

- **`ned_folders`** — directories containing `.ned` files.
- **`cpp_folders`** / **`msg_folders`** — C++ and MSG source directories.
- **`ini_file_folders`** — directories scanned recursively for `*.ini`
  files to discover simulation configs.
- **`bin_folder`** / **`library_folder`** — where built executables and
  libraries are placed.
- **`python_folders`** — Python source directories (e.g. `"python"`).

## Build types

The `build_types` parameter determines how the project is compiled:

- `"dynamic library"` (default) — builds a shared library loaded by
  `opp_run`.
- `"executable"` — builds a standalone executable.

When using dynamic libraries, the project's `opp_run` comes from its
`OmnetppProject`; when using executables, the project provides its own
binary.

## Dependencies

- **`omnetpp_project`** — the OMNeT++ installation to use.  Can be an
  `OmnetppProject` instance or a string name that is resolved from the
  workspace.
- **`used_projects`** — a list of other simulation project names that this
  project depends on (e.g. `["inet"]` for Simu5G).  Dependencies are
  resolved from the workspace by name.

When building, dependencies are built recursively (OMNeT++ first, then
used projects, then the project itself).

## Discovering simulation configs

Calling `get_simulation_configs()` scans all `ini_file_folders` for `*.ini`
files and parses them to discover `[Config ...]` sections.  The results are
cached after the first call.  You can filter them with the standard filter
parameters:

```python
p = get_simulation_project("inet")
configs = p.get_simulation_configs(working_directory_filter="examples/ethernet")
```

## Building and cleaning

Building compiles the project and all its dependencies (OMNeT++ and
`used_projects`).  Cleaning removes all build artifacts.

```python
p.build(mode="release")       # build (recursively: omnetpp, deps, then self)
p.build(mode="debug")
p.clean(mode="release")       # clean all build artifacts
```

The `recursive=True` default means OMNeT++ and all `used_projects` are
built first.

## Overlay builds

Like `OmnetppProject`, simulation projects support `overlay_name` for
out-of-tree builds via fuse-overlayfs.  This is useful for testing patches
or comparing two versions without modifying the original source tree.
See [Overlay builds](overlay_builds.md).

```python
# ~/workspace/inet/inet+omnetpp.opp
SimulationProject(
    name="inet+omnetpp",
    root_folder=".",
    omnetpp_project="omnetpp",
    overlay_name="inet+omnetpp",
    library_folder="src",
    bin_folder="bin",
    dynamic_libraries=["INET"],
    ned_folders=["src", "examples", "showcases", "tutorials"],
    ini_file_folders=["examples"],
)
```

## opp_env integration

Set `opp_env_workspace` and `opp_env_project` to route build and run
commands through the `opp_env` tool for projects managed by opp_env.

```python
SimulationProject(
    name="inet-4.6.0",
    root_folder=".",
    omnetpp_project="omnetpp-6.3.0",
    opp_env_workspace="/home/user/opp_env",
    opp_env_project="inet-4.6.0",
    library_folder="src",
    bin_folder="bin",
    dynamic_libraries=["INET"],
    ned_folders=["src", "examples", "showcases", "tutorials"],
    ini_file_folders=["examples"],
)
```

## Test and result stores

Several test types use per-project stores for baselines:

- **`fingerprint_store`** — path to the JSON file with expected
  fingerprints (default: `"fingerprint.json"`).
- **`speed_store`** — path to the JSON file with baseline speed
  measurements (default: `"speed.json"`).
- **`statistics_folder`** — folder for baseline scalar results.
- **`media_folder`** — folder for baseline chart images.

## GitHub integration

The optional `github_owner`, `github_repository`, and `github_workflows`
parameters enable dispatching GitHub Actions workflows from the REPL or
command line.

## Looking up projects

At REPL startup, every loaded simulation project is injected as a
convenience variable `{name}_project` (hyphens and dots become underscores),
e.g. `inet_project`, `simu5g_project`.  Projects can also be looked up by
name:

```python
inet_project                            # convenience variable
get_simulation_project("inet")          # look up by name
get_simulation_project("inet", "4.5")   # look up by name and version
get_simulation_project_names()          # all registered names
get_default_simulation_project()        # the current default
```

The default simulation project is determined automatically at startup based
on the current working directory.  See [Simulation workspaces](simulation_workspaces.md)
for details on how projects are registered, resolved, and defaulted.

## Inspecting a project

All parameters passed in the `.opp` file are available as attributes on the
project object:

```python
p = get_simulation_project("fifo")
p.name                # 'fifo'
p.root_folder         # '/home/user/workspace/omnetpp/samples/fifo'
p.ini_file_folders    # ['.']
p.ned_folders         # ['.']
p.build_types         # ['executable']
```
