# Running Simulations

## Building Projects

It's essential to make sure that the simulation project is built before running a simulation.
opp_repl supports building the simulation project using Python functions:

```python
p = get_simulation_project("inet")
build_project(simulation_project=p)
build_project(simulation_project=p, mode="debug")
```

The `build_project()` function runs the `make` command in the project root directory.
The `mode` parameter selects the build mode (see Concepts guide for available modes).

Note: `run_simulations()` automatically builds the project unless `build=False` is passed.

## Running Simulations

The `run_simulations()` function can run multiple simulations matching filter criteria.
Simulations can run sequentially or concurrently, on the local computer or on an SSH cluster.

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

You can control many aspects of running simulations:
- `mode` — choose between release, debug, sanitize, coverage, profile
- `sim_time_limit`, `cpu_time_limit` — control termination
- `concurrent` — enable/disable parallel execution
- `scheduler` — choose local or cluster execution
- `simulation_runner` — choose subprocess, opp_env, inprocess, or ide runner
- `build` — set to `False` to skip automatic building

### Getting tasks without running

The `get_simulation_tasks()` function returns a list of tasks that can be stored,
passed around, and run later:

```python
mt = get_simulation_tasks(simulation_project=p, mode="release",
                          filter="PureAlohaExperiment")
mt.run()
```

### Cancelling simulations

Pressing Control-C cancels execution of remaining simulations. The result object
still contains all results collected up to the cancellation point.

## Command Line

```bash
# Run all simulations from the fifo sample project (uses current working directory)
cd ~/workspace/omnetpp/samples/fifo
opp_run_simulations

# Run on a SSH cluster in debug mode with a filter and time limit
opp_run_simulations -m debug -t 1s --filter PureAlohaExperiment --hosts node1.local,node2.local
```

## Loading Projects at Runtime

```python
load_opp_file("/path/to/project.opp")
load_opp_file("/path/to/workspace/*/*.opp")  # glob patterns supported
```

## Cleaning Results

```python
clean_simulation_results(simulation_project=inet_project)
clean_simulation_results(simulation_project=inet_project,
                         working_directory_filter="examples/ethernet")
```
