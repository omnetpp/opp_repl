# Simulation Workspaces

A `SimulationWorkspace` is a **registry** that holds all loaded
`OmnetppProject` and `SimulationProject` instances.  It is the top-level
container in the opp_repl object hierarchy.

## The default workspace

opp_repl creates a default workspace automatically at startup.  Every
`.opp` file loaded via `--load` on the command line (or `load_opp_file()`
at runtime) is registered here.  You rarely need to interact with the
workspace directly — the module-level helper functions delegate to it
behind the scenes:

```python
get_default_simulation_workspace()   # access it explicitly if needed
get_simulation_project("inet")       # delegates to the default workspace
get_simulation_project_names()       # lists all registered project names
```

## Loading projects

Projects enter the workspace through `.opp` descriptor files.  There are
several ways to load them:

```python
# Load a single file
load_opp_file("~/workspace/inet/inet.opp")

# Load with a glob pattern
load_opp_file("~/workspace/omnetpp/samples/*/*.opp")

# Scan an entire workspace directory (loads all *.opp under it)
load_workspace("~/workspace")
```

When loading multiple files, **OmnetppProject files are always processed
first**, so that simulation projects can reference them by name.

## Project lookup

Projects are registered as `(name, version)` pairs.  Most of the time the
version is `None` (meaning "the only version"), and you look up projects by
name:

```python
p = get_simulation_project("inet")
```

When multiple versions of the same project are loaded, pass the version
explicitly:

```python
p = get_simulation_project("inet", version="4.5")
```

## Resolving project designators

The `resolve_simulation_project()` function accepts flexible designator
strings:

- **Name** — `"inet"` looks up the registered project.
- **Name:version** — `"inet:4.5"` looks up a specific version.
- **Folder path** — `"../inet-baseline"` or an absolute path finds the
  project at that location (auto-loading its `.opp` file if not already
  registered).

This is used internally by functions like `compare_simulations()` that
accept a project designator for the comparison target.

## The default project

One project in the workspace is designated as the **default**.  It is set
automatically at startup to the project whose root folder contains the
current working directory.  It can also be set explicitly:

```python
set_default_simulation_project(inet_project)
```

Functions like `run_simulations()`, `run_fingerprint_tests()`, and
`build_project()` use the default project when no `simulation_project`
argument is given.

Setting the default project also sets the **default OMNeT++ project**: if
the simulation project references an `OmnetppProject`, that becomes the
default; otherwise the project registered under the name `"omnetpp"` is
used as a fallback.
