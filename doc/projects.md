# Projects

Simulation projects are the central unit of work in opp_repl.  This guide
explains how to discover, inspect, and select them.

## Listing loaded projects

```python
# List all registered simulation project names
get_simulation_project_names()
# → ['aloha', 'canvas', 'cqn', 'fifo', 'inet', 'simu5g', ...]
```

## Getting a project by name

```python
p = get_simulation_project("fifo")
```

An optional `version` parameter selects a specific version when multiple
versions of the same project are loaded:

```python
p = get_simulation_project("inet", version="4.6.0")
```

## Default project

Many functions (`run_simulations()`, `build_project()`, `run_smoke_tests()`,
etc.) accept an optional `simulation_project` parameter.  When omitted, they
use the **default simulation project**.

The default is set automatically at startup to the loaded project whose root
folder contains the current working directory.  It can also be set explicitly:

```python
# Set programmatically
set_default_simulation_project(get_simulation_project("fifo"))

# Query the current default
get_default_simulation_project()
```

On the command line, use `-p PROJECT` to select the default project at startup.

## Convenience variables

At REPL startup, every loaded simulation project is injected into the
namespace as `{name}_project` (hyphens and dots become underscores):

```python
fifo_project          # same as get_simulation_project("fifo")
inet_project          # same as get_simulation_project("inet")
inet_omnetpp_project  # same as get_simulation_project("inet+omnetpp")
```

## Loading projects at runtime

Projects are defined by `.opp` descriptor files and loaded with `load_opp_file()`:

```python
load_opp_file("/path/to/project.opp")
load_opp_file("/home/user/workspace/*/*.opp")  # glob patterns supported
```

See the **opp_files** guide for the `.opp` file format.

## Inspecting a project

A `SimulationProject` exposes its configuration:

```python
p = get_simulation_project("fifo")
p.name                # 'fifo'
p.root_folder         # '/home/user/workspace/omnetpp/samples/fifo'
p.ini_file_folders    # ['.']
p.ned_folders         # ['.']
p.build_types         # ['executable']
```

## Listing simulation configs

Each project contains simulation configs discovered from its INI files:

```python
p = get_simulation_project("fifo")
configs = p.get_simulation_configs()
for c in configs:
    print(c.config, c.num_runs)
# Fifo1 1
# Fifo2 1
# TandemQueues 1
# TandemQueueExperiment 4
```

## Quick example

```python
# List projects, pick one, run all its simulations
get_simulation_project_names()
run_simulations(simulation_project=get_simulation_project("fifo"))
```
