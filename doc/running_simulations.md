# Running Simulations

Build simulation projects, run simulations with various filters and modes,
handle results, and manage project loading and cleanup.

## Building Projects

Building is implicit: `run_simulations()` automatically builds the project
before running any simulation, so there is no need to build manually.  Stale
binaries are not used by default — the build step ensures the binary is
up-to-date with the current sources.  Pass `build=False` to skip this step
when you know the binary is already current.

If you need to trigger a build without running simulations, use
`build_project()` directly:

```python
p = get_simulation_project("inet")
build_project(simulation_project=p)
build_project(simulation_project=p, mode="debug")
```

The `mode` parameter selects the build mode (see Concepts guide for available modes).

## Running Simulations

The `run_simulations()` function can run multiple simulations matching filter criteria.
Simulations can run sequentially or concurrently, on the local computer or on an SSH cluster.

> **Tip:** Every loaded project is available as a `{name}_project` variable
> (hyphens/dots become underscores).  Use `get_simulation_project_variable_names()`
> to list them.

```python
# Run all simulations from a project
run_simulations(simulation_project=fifo_project)

# Run with a config filter and time limit
run_simulations(simulation_project=aloha_project,
                config_filter="PureAlohaExperiment", sim_time_limit="1s")

# Run in debug mode
run_simulations(simulation_project=inet_project,
                working_directory_filter="examples/ethernet",
                mode="debug", sim_time_limit="10s")
```

The order of simulation runs may vary because they run in parallel utilizing all CPUs by default.

### Using the default project

Setting a default simulation project simplifies function calls:

```python
set_default_simulation_project(get_simulation_project("fifo"))
run_simulations()  # uses default project
```

The same effect can be achieved by starting the Python interpreter from the project directory,
or by using the `-p PROJECT` command-line option.

### Handling results

`run_simulations()` returns a `MultipleTaskResults` object:

```python
r = run_simulations(config_filter="PureAloha", sim_time_limit="1s")

# Re-run the same simulations
r = r.rerun()

# Re-run only failed simulations
r.get_error_results().rerun()
```

### Controlling execution

See [Simulation tasks](tasks.md) for details on build modes, runners,
concurrency options, cancellation, and `get_simulation_tasks()`.

## Command Line

When no `--load` option is given, all `*.opp` files in the current working
directory are loaded automatically.  This means you can simply `cd` into a
project directory that contains `.opp` files and run simulations without any
extra arguments:

```bash
# Run all simulations from the fifo sample project (*.opp files loaded from CWD)
cd ~/workspace/omnetpp/samples/fifo
opp_run_simulations

# Explicitly load a .opp file from a different location
opp_run_simulations --load /path/to/aloha.opp --filter PureAloha -t 1s

# Run on a SSH cluster in debug mode with a filter and time limit
opp_run_simulations -m debug -t 1s --filter PureAlohaExperiment --hosts node1.local,node2.local
```

> **Note:** The OMNeT++ project is auto-detected from the `__omnetpp_root_dir`
> environment variable (set by the OMNeT++ `setenv` script).  You only need to
> load an `omnetpp.opp` file explicitly when using a non-standard installation.
> See [OMNeT++ projects — Automatic detection](omnetpp_projects.md#automatic-detection).

## Loading projects at runtime

See [Simulation workspaces](simulation_workspaces.md) for `load_opp_file()`
and `load_workspace()`.

## Cleaning Results

```python
clean_simulation_results(simulation_project=inet_project)
clean_simulation_results(simulation_project=inet_project,
                         working_directory_filter="examples/ethernet")
```
