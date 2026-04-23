# Concepts

opp_repl is organized around a hierarchy of concepts that mirror the
structure of OMNeT++ simulation projects.

## OmnetppProject

Represents a specific **OMNeT++ installation** on disk.  It knows where to
find the `opp_run` executable, which build modes are available, and how to
compile OMNeT++ itself.  Every simulation project references an
`OmnetppProject` (either explicitly or via a global default).

For local installations the root folder is typically resolved from an
environment variable or an explicit path.  For opp_env-managed installations
the `opp_env_workspace` and `opp_env_project` parameters tell opp_repl to
route build and run commands through `opp_env run`.

## SimulationProject

Represents a **simulation model project** — a codebase that contains NED
modules, C++ sources, and example simulations.  Examples include INET,
Simu5G, or any of the OMNeT++ sample projects (aloha, fifo, tictoc, …).

A simulation project knows:
- **where the sources live** — `root_folder`, `library_folder`, `bin_folder`,
  `ned_folders`, `cpp_folders`, `msg_folders`
- **what to build** — `build_types` (`"executable"` or `"dynamic library"`),
  `executables`, `dynamic_libraries`
- **where the simulations are** — `ini_file_folders` (scanned for `*.ini` files)
- **what it depends on** — `omnetpp_project` (the OMNeT++ to use),
  `used_projects` (other simulation projects like INET)

The project also supports **overlay builds** (via fuse-overlayfs) for
testing patches without modifying the original source tree, and
**opp_env** integration for projects managed by the `opp_env` tool.

## SimulationConfig

Represents a single **`[Config …]` section** from one INI file within a
simulation project.  It is automatically discovered by scanning the
`ini_file_folders` of the project.

Key properties:
- **`working_directory`** — the folder containing the INI file (relative to
  the project root)
- **`ini_file`** — the INI file name (e.g. `omnetpp.ini`)
- **`config`** — the section name (e.g. `"General"`, `"PureAlohaExperiment"`)
- **`num_runs`** — the total number of runs, determined from iteration
  variables like `${x=1,2,3}` and `repeat=N` in the INI file
- **`abstract`** — if `true`, the config is meant to be extended, not run
  directly
- **`sim_time_limit`** — the simulation time limit from the INI file, if any

## SimulationTask

Represents a **single simulation run** — one specific (config, run number)
combination that can be executed as a subprocess.  A simulation task is
fully parameterized: it knows the config, the run number, the build mode,
any overridden time limits, etc.

Tasks are created by `get_simulation_tasks()` which expands each
`SimulationConfig` into `num_runs` individual tasks (one per run number).

## Build Modes

Both `build_project()` and `run_simulations()` accept a `mode` parameter.
The available modes are:

| Mode | Suffix | Use case |
|---|---|---|
| `release` | `_release` | Normal optimized builds (default) |
| `debug` | `_dbg` | Debug builds for stepping through code |
| `sanitize` | `_sanitize` | AddressSanitizer / UBSan builds |
| `coverage` | `_coverage` | Code coverage instrumented builds |
| `profile` | `_profile` | Performance profiling builds |

## Simulation Runners

A simulation task can be executed by different **runners**, selected via
the `simulation_runner` parameter of `run_simulations()`:

- **`subprocess`** *(default)* — launches the simulation as a child
  process.
- **`opp_env`** — routes the command through `opp_env run` for
  opp_env-managed installations (selected automatically when the project
  has `opp_env_workspace` set).
- **`inprocess`** — runs the simulation inside the Python process via
  CFFI (requires `omnetpp.cffi`).
- **`ide`** — attaches the IDE debugger to the simulation (selected
  automatically when `debug=True`).

## SimulationTaskResult

The **outcome of running a task** — captures the return code, stdout/stderr,
elapsed wall time, error messages, last event number and simulation time,
and result files (`.sca`, `.vec`, `.elog`).  Results are classified as
`DONE`, `ERROR`, `CANCEL`, or `SKIP`.

## MultipleSimulationTasks / MultipleTaskResults

Running simulations typically involves many tasks at once.
`run_simulations()` returns a `MultipleTaskResults` object that summarizes
the overall outcome and provides methods to filter (e.g. `get_error_results()`)
and re-run subsets.

## SimulationWorkspace

A **registry** that holds all loaded `OmnetppProject` and
`SimulationProject` instances.  Projects are registered by loading `.opp`
descriptor files via `--load` on the command line or `load_opp_file()` at
runtime.

## Defaults

opp_repl maintains three global defaults so that most functions can be
called without explicitly specifying a workspace or project:

- **Default workspace** — a `SimulationWorkspace` instance created
  automatically at startup.  All `.opp` files loaded via `--load` (or
  `load_opp_file()` at runtime) are registered here.  Access it with
  `get_default_simulation_workspace()`.

- **Default simulation project** — set at startup to the loaded project
  whose root folder contains the current working directory.  It can also
  be set explicitly with `-p PROJECT` on the command line or
  `set_default_simulation_project()` at runtime.  Functions like
  `run_simulations()`, `run_smoke_tests()`, and `build_project()` use
  it when no `simulation_project` argument is given.  Access it with
  `get_default_simulation_project()`.

- **Default OMNeT++ project** — set automatically when the default
  simulation project is determined: if the simulation project references
  an `OmnetppProject` (via its `omnetpp_project` parameter), that
  becomes the default; otherwise the project registered under the name
  `"omnetpp"` is used as a fallback.  Access it with
  `get_default_omnetpp_project()`.

At REPL startup, every loaded simulation project is also injected into
the IPython namespace as a convenience variable named
`{name}_project` (with hyphens and dots replaced by underscores).  For
example, loading a project named `"inet"` creates a variable
`inet_project`, and `"simu5g"` creates `simu5g_project`.

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
