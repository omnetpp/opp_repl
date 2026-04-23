# Concepts

opp_repl is organized around a hierarchy of concepts that mirror the
structure of OMNeT++ simulation projects.

## SimulationWorkspace

A **registry** that holds all loaded projects and manages defaults.
See [Simulation workspaces](simulation_workspaces.md).

## OmnetppProject

Represents a specific **OMNeT++ installation** on disk — locates
executables, sets up the environment, and builds OMNeT++ itself.
See [OMNeT++ projects](omnetpp_projects.md).

## SimulationProject

Represents a **simulation model project** (e.g. INET, Simu5G) — knows
where sources, NED files, and INI files live, what to build, and what it
depends on.  See [Simulation projects](simulation_projects.md).

## SimulationConfig

A single **`[Config …]` section** from an INI file — working directory,
config name, number of runs, time limit, abstract/emulation flags.
See [Simulation configs](simulation_configs.md).

## SimulationTask

A **single simulation run** — one (config, run number) combination with
all parameters needed to execute it.
See [Simulation tasks](tasks.md).

## SimulationTaskResult / MultipleTaskResults

The **outcome** of running one or more tasks — result codes, timing,
error details, filtering, and re-running.
See [Task results](task_results.md).

## How they fit together

```
SimulationWorkspace
 ├── OmnetppProject  "omnetpp"         (OMNeT++ installation)
 ├── SimulationProject  "inet"         (model project)
 │    ├── SimulationConfig  examples/ethernet/simple  -c General   (1 run)
 │    ├── SimulationConfig  examples/wireless/nic     -c Wifi      (10 runs)
 │    │    ├── SimulationTask  run #0
 │    │    ├── SimulationTask  run #1
 │    │    └── …
 │    └── …
 └── SimulationProject  "simu5g"       (depends on inet)
      └── …
```

## Filtering

Most functions that operate on simulation configs accept **regex-based
include/exclude filter pairs** to narrow down what is selected.  The
filters are regular expressions matched against the corresponding
property; a config is included only when all specified filters match.

| Include filter | Exclude filter | Matches against |
|---|---|---|
| `filter` | `exclude_filter` | full config string representation |
| `working_directory_filter` | `exclude_working_directory_filter` | working directory path |
| `ini_file_filter` | `exclude_ini_file_filter` | INI file name |
| `config_filter` | `exclude_config_filter` | config section name |
| `run_number_filter` | `exclude_run_number_filter` | run number (as string) |

In addition, the `simulation_config_filter` parameter accepts a
**predicate function** that receives each `SimulationConfig` and returns
`True`/`False`.  By default it excludes abstract and emulation configs.

Setting `full_match=True` requires the regex to match the entire string
rather than just a substring.

These filters are available on `run_simulations()`, `run_smoke_tests()`,
`run_fingerprint_tests()`, `compare_simulations()`, and all other
functions that call `get_simulation_tasks()` internally.
