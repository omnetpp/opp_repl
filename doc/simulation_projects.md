# Simulation Projects

A `SimulationProject` represents a **simulation model project** — a
codebase that contains NED modules, C++ sources, and example simulations.
Examples include INET, Simu5G, or any of the OMNeT++ sample projects.

## Defining a project

Projects are defined in `.opp` descriptor files (see
[OPP files](opp_files.md) for the full format).  A minimal example:

```python
SimulationProject(
    name="inet",
    root_folder="/home/user/workspace/inet",
    omnetpp_project="omnetpp",
    used_projects=["omnetpp"],
    ned_folders=["src/inet", "examples", "showcases", "tutorials"],
    ini_file_folders=["examples", "showcases", "tutorials"],
)
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

## opp_env integration

Set `opp_env_workspace` and `opp_env_project` to route build and run
commands through the `opp_env` tool for projects managed by opp_env.

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

## Listing and looking up projects

```python
get_simulation_project_names()          # all registered names
get_simulation_project("inet")          # look up by name
get_simulation_project("inet", "4.5")   # look up by name and version
```

At REPL startup, every loaded project is also injected as a convenience
variable `{name}_project` (hyphens and dots become underscores), e.g.
`inet_project`, `simu5g_project`.

See [Simulation workspaces](simulation_workspaces.md) for details on how
projects are registered, resolved, and defaulted.

## Inspecting a project

```python
p = get_simulation_project("fifo")
p.name                # 'fifo'
p.root_folder         # '/home/user/workspace/omnetpp/samples/fifo'
p.ini_file_folders    # ['.']
p.ned_folders         # ['.']
p.build_types         # ['executable']
```
