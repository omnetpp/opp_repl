# opp_repl

An interactive Python REPL for OMNeT++ — run simulations, smoke tests,
fingerprint tests, and more from an IPython shell.

## Installation

Requires Python 3.10+.

```bash
pip install -e .
```

Optional extras:

```bash
pip install -e ".[all]"     # install every optional group
pip install -e ".[cluster]" # just one group
```

| Extra | Packages | Purpose |
|---|---|---|
| `cluster` | dask, distributed | SSH cluster execution via Dask |
| `chart` | matplotlib, numpy | Chart tests and image export |
| `mcp` | mcp | MCP server for AI assistant integration |
| `optimize` | scipy, optimparallel | Parameter optimization |
| `github` | requests | GitHub API integration |
| `ide` | py4j | OMNeT++ IDE integration |
| `all` | *(all of the above)* | Everything |

## Quick Start

```bash
# Start the REPL, loading project descriptors
opp_repl --load ~/workspace/omnetpp/omnetpp.opp \
         --load "~/workspace/omnetpp/samples/*/*.opp"

# Or load opp_env-managed projects
opp_repl --load "~/opp_env/**/*.opp"

# Multiple --load arguments can be combined
opp_repl --load ~/workspace/omnetpp/omnetpp.opp \
         --load "~/workspace/omnetpp/samples/*/*.opp" \
         --load ~/workspace/inet/inet.opp
```

Once inside the REPL:

```python
In [1]: run_simulations(simulation_project=fifo_project)
```

## Command-Line Options

```
opp_repl [-h]
         [-p PROJECT]              # set default simulation project by name
         [-l {ERROR,WARN,INFO,DEBUG}]  # log level (default: INFO)
         [--external-command-log-level {ERROR,WARN,INFO,DEBUG}]
         [--mcp-port PORT]         # MCP server port, 0 to disable (default: 0)
         [--load OPP_FILE]         # load .opp file(s), repeatable, supports globs
         [--handle-exception | --no-handle-exception]
```

## Concepts

opp_repl is organized around a hierarchy of concepts that mirror the
structure of OMNeT++ simulation projects.

### OmnetppProject

Represents a specific **OMNeT++ installation** on disk.  It knows where to
find the `opp_run` executable, which build modes are available, and how to
compile OMNeT++ itself.  Every simulation project references an
`OmnetppProject` (either explicitly or via a global default).

For local installations the root folder is typically resolved from an
environment variable or an explicit path.  For opp_env-managed installations
the `opp_env_workspace` and `opp_env_project` parameters tell opp_repl to
route build and run commands through `opp_env run`.

### SimulationProject

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

### SimulationConfig

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

### SimulationTask

Represents a **single simulation run** — one specific (config, run number)
combination that can be executed as a subprocess.  A simulation task is
fully parameterized: it knows the config, the run number, the build mode,
any overridden time limits, etc.

Tasks are created by `get_simulation_tasks()` which expands each
`SimulationConfig` into `num_runs` individual tasks (one per run number).

### Build Modes

Both `build_project()` and `run_simulations()` accept a `mode` parameter.
The available modes are:

| Mode | Suffix | Use case |
|---|---|---|
| `release` | `_release` | Normal optimized builds (default) |
| `debug` | `_dbg` | Debug builds for stepping through code |
| `sanitize` | `_sanitize` | AddressSanitizer / UBSan builds |
| `coverage` | `_coverage` | Code coverage instrumented builds |
| `profile` | `_profile` | Performance profiling builds |

### Simulation Runners

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

### SimulationTaskResult

The **outcome of running a task** — captures the return code, stdout/stderr,
elapsed wall time, error messages, last event number and simulation time,
and result files (`.sca`, `.vec`, `.elog`).  Results are classified as
`DONE`, `ERROR`, `CANCEL`, or `SKIP`.

### MultipleSimulationTasks / MultipleTaskResults

Running simulations typically involves many tasks at once.
`run_simulations()` returns a `MultipleTaskResults` object that summarizes
the overall outcome and provides methods to filter (e.g. `get_error_results()`)
and re-run subsets.

### SimulationWorkspace

A **registry** that holds all loaded `OmnetppProject` and
`SimulationProject` instances.  Projects are registered by loading `.opp`
descriptor files via `--load` on the command line or `load_opp_file()` at
runtime.

### Defaults

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

### How they fit together

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

### Filtering

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

## Project Descriptor Files (`.opp`)

Projects are described by `.opp` files — small Python expressions that
define either an `OmnetppProject` or a `SimulationProject`.  They use a
restricted syntax: a single constructor call with keyword-only literal
arguments (strings, numbers, booleans, lists, dicts, `None`).

### OmnetppProject

Describes an OMNeT++ installation.

```python
OmnetppProject(
    name="omnetpp",
)
```

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `name` | `str` | Human-readable name for this OMNeT++ installation |
| `environment_variable` | `str` | OS environment variable pointing to the root folder (default: `"__omnetpp_root_dir"`) |
| `root_folder` | `str` | Explicit root folder path (overrides `environment_variable`) |
| `overlay_key` | `str` | Enable overlay builds via fuse-overlayfs with this key |
| `build_root` | `str` | Override the overlay build root directory |
| `opp_env_workspace` | `str` | Path to opp_env workspace (for opp_env-managed installations) |
| `opp_env_project` | `str` | opp_env project identifier (e.g. `"omnetpp-6.3.0"`) |

### SimulationProject

Describes a simulation project (INET, Simu5G, OMNeT++ samples, etc.).

```python
SimulationProject(
    name="fifo",
    omnetpp_project="omnetpp",
    build_types=["executable"],
    ned_folders=["."],
    ini_file_folders=["."],
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | *(required)* | Human-readable project name |
| `version` | `str` | `None` | Version string |
| `omnetpp_project` | `str` | `None` | Name of the `OmnetppProject` to use (resolved lazily) |
| `root_folder` | `str` | auto | Root folder (auto-set to the `.opp` file's directory) |
| `folder` | `str` | `"."` | Project directory relative to root |
| `bin_folder` | `str` | `"."` | Binary output directory relative to root |
| `library_folder` | `str` | `"."` | Library output directory relative to root |
| `build_types` | `list[str]` | `["dynamic library"]` | Build output types: `"executable"`, `"dynamic library"`, `"static library"` |
| `executables` | `list[str]` | `None` | Executable names to build |
| `dynamic_libraries` | `list[str]` | `None` | Dynamic library names to build |
| `ned_folders` | `list[str]` | `["."]` | Directories containing NED files |
| `ned_exclusions` | `list[str]` | `[]` | Excluded NED packages |
| `ini_file_folders` | `list[str]` | `["."]` | Directories containing INI files |
| `used_projects` | `list[str]` | `[]` | Names of dependent simulation projects |
| `media_folder` | `str` | `"."` | Directory for chart test baseline images |
| `statistics_folder` | `str` | `"."` | Directory for statistical test baseline results |
| `fingerprint_store` | `str` | `"fingerprint.json"` | Path to the JSON fingerprint store |
| `speed_store` | `str` | `"speed.json"` | Path to the JSON speed measurement store |
| `overlay_key` | `str` | `None` | Enable overlay builds with this key |
| `build_root` | `str` | `None` | Override overlay build root |
| `opp_env_workspace` | `str` | `None` | Path to opp_env workspace |
| `opp_env_project` | `str` | `None` | opp_env project identifier (e.g. `"inet-4.6.0"`) |
| `github_owner` | `str` | `None` | GitHub owner/organization for workflow dispatch |
| `github_repository` | `str` | `None` | GitHub repository name for workflow dispatch |
| `github_workflows` | `list[str]` | `None` | GitHub Actions workflow file names (e.g. `["fingerprint-tests.yml"]`) |

## Example `.opp` Files

### Standalone OMNeT++ sample (executable)

```python
# ~/workspace/omnetpp/samples/aloha/aloha.opp
SimulationProject(
    name="aloha",
    omnetpp_project="omnetpp",
    build_types=["executable"],
    ned_folders=["."],
    ini_file_folders=["."],
)
```

### INET Framework (dynamic library)

```python
# ~/workspace/inet/inet.opp
SimulationProject(
    name="inet",
    library_folder="src",
    bin_folder="bin",
    build_types=["dynamic library"],
    dynamic_libraries=["INET"],
    ned_folders=["src", "examples", "showcases", "tutorials", "tests/networks"],
    ini_file_folders=["examples", "showcases", "tutorials", "tests/fingerprint"],
    media_folder="doc/media",
    statistics_folder="statistics",
    fingerprint_store="tests/fingerprint/store.json",
    speed_store="tests/speed/store.json",
    github_owner="inet-framework",
    github_repository="inet",
    github_workflows=[
        "fingerprint-tests.yml",
        "statistical-tests.yml",
        "chart-tests.yml",
    ],
)
```

### INET with explicit OMNeT++ and overlay builds

```python
# ~/workspace/inet/inet+omnetpp.opp
SimulationProject(
    name="inet+omnetpp",
    omnetpp_project="omnetpp",
    overlay_key="inet+omnetpp",
    library_folder="src",
    bin_folder="bin",
    build_types=["dynamic library"],
    dynamic_libraries=["INET"],
    ned_folders=["src", "examples", "showcases", "tutorials", "tests/networks"],
    ini_file_folders=["examples"],
)
```

### Simu5G (depends on INET)

```python
# ~/workspace/simu5g/simu5g.opp
SimulationProject(
    name="simu5g",
    omnetpp_project="omnetpp",
    library_folder="src",
    bin_folder="bin",
    build_types=["dynamic library"],
    dynamic_libraries=["simu5g"],
    used_projects=["inet"],
    ned_folders=["src", "simulations"],
    ini_file_folders=["simulations"],
)
```

### opp_env-managed OMNeT++ installation

```python
# ~/opp_env/omnetpp-6.3.0/omnetpp.opp
OmnetppProject(
    name="omnetpp-6.3.0-opp_env",
    opp_env_workspace="/home/user/opp_env",
    opp_env_project="omnetpp-6.3.0",
)
```

### opp_env-managed INET

```python
# ~/opp_env/inet-4.6.0/inet-4.6.0.opp
SimulationProject(
    name="inet-4.6.0-opp_env",
    omnetpp_project="omnetpp-6.3.0-opp_env",
    opp_env_project="inet-4.6.0",
    opp_env_workspace="/home/user/opp_env",
    library_folder="src",
    bin_folder="bin",
    build_types=["dynamic library"],
    dynamic_libraries=["INET"],
    ned_folders=["src", "examples", "showcases", "tutorials", "tests/networks"],
    ini_file_folders=["examples"],
)
```

## Usage Examples

### Running simulations

```python
# Run all simulations from a project
run_simulations(simulation_project=fifo_project)

# Run with a filter and time limit
run_simulations(simulation_project=aloha_project,
                filter="PureAloha1", sim_time_limit="1s")

# Run a specific config
run_simulations(simulation_project=aloha_project,
                config_filter="PureAlohaExperiment", sim_time_limit="1s")

# Run in debug mode
run_simulations(simulation_project=inet_project,
                working_directory_filter="examples/ethernet",
                mode="debug", sim_time_limit="10s")

# Re-run failed simulations
r = run_simulations(...)
r.get_error_results().rerun()
```

### Building projects

```python
build_project(simulation_project=inet_project)
build_project(simulation_project=inet_project, mode="debug")
```

### Smoke tests

Quick sanity checks — run every simulation for a short time to catch
crashes and obvious errors.

```python
run_smoke_tests()
run_smoke_tests(simulation_project=aloha_project,
                config_filter="PureAlohaExperiment")
```

### Fingerprint tests

Fingerprint tests detect unintended behavioral changes by comparing a
hash of selected simulation state (trajectory, packet counts, etc.)
against stored baseline values.  The baseline is kept in a JSON store
file configured via the `fingerprint_store` project parameter.

```python
# Store correct fingerprints (first time, or after intentional changes)
update_correct_fingerprints(simulation_project=inet_project, sim_time_limit="1s")

# Verify against stored values
r = run_fingerprint_tests(simulation_project=inet_project, sim_time_limit="1s")

# Re-run only the failures
r.get_fail_results().rerun()

# Filter to a specific area of the project
run_fingerprint_tests(simulation_project=inet_project,
                      working_directory_filter="examples/ethernet",
                      sim_time_limit="10s")

# Update fingerprints for a subset after intentional changes
update_correct_fingerprints(simulation_project=inet_project,
                            working_directory_filter="examples/ethernet",
                            sim_time_limit="10s")
```

From the command line:

```bash
# Store correct fingerprints for the fifo sample project
opp_update_correct_fingerprints --load "/home/levy/workspace/omnetpp/**/*.opp" -p fifo
```

```
[0/8] ▶ 7 fifo update fingerprints (concurrently)
[1/8]   ⏺ Updating fingerprint . -c TandemQueueExperiment -r 2 for 200s INSERT b654-75cc/tplx
...
[8/8] ◉ 7 fifo update fingerprints (concurrently) Multiple update fingerprints: 7 INSERT in 2.431
```

```bash
# Verify against stored values
opp_run_fingerprint_tests --load "/home/levy/workspace/omnetpp/**/*.opp" -p fifo
```

```
[00/8] ▶ 7 fifo fingerprint tests (concurrently)
[01/8]   ⏺ Checking fingerprint . -c TandemQueueExperiment -r 2 for 200s PASS in 0.015
...
[08/8] ◉ 7 fifo fingerprint tests (concurrently) Multiple fingerprint tests: 7 PASS in 3.01
```

### Statistical tests

Statistical tests detect regressions in simulation scalar results by
comparing them against saved baseline values.  The baseline is stored
in the `statistics_folder` of the project.

```python
# Store baseline results (first time, or after intentional changes)
update_statistical_results(simulation_project=inet_project)

# Run tests — compares current results against the baseline
run_statistical_tests(simulation_project=inet_project)

# Filter to a specific area
run_statistical_tests(simulation_project=inet_project,
                      working_directory_filter="examples/ethernet")
```

### Chart tests

Chart tests detect visual regressions in result analysis charts by
comparing rendered images against saved baseline images.  The baseline
is stored in the `media_folder` of the project.

```python
# Store baseline charts (first time, or after intentional changes)
update_charts(simulation_project=inet_project)

# Run tests — compares current charts against the baseline
run_chart_tests(simulation_project=inet_project)

# Filter by working directory or chart name
run_chart_tests(simulation_project=inet_project,
                working_directory_filter="showcases")
```

### Speed tests

Speed tests detect performance regressions by measuring CPU instruction
counts and comparing them against stored baseline values.  Uses the
`profile` build mode and the `speed_store` JSON file.

```python
# Store baseline measurements (first time, or after intentional changes)
update_speed_results(simulation_project=inet_project)

# Run tests — compares current measurements against the baseline
run_speed_tests(simulation_project=inet_project)

# Filter to specific simulations
run_speed_tests(simulation_project=inet_project,
                working_directory_filter="showcases")
```

### Parameter optimization

Find simulation parameter values that produce desired results by iteratively
running simulations and minimizing the difference from a target.  Uses
`scipy.optimize` with Nelder-Mead (derivative-free, suitable for stochastic
simulations).

**Example 1 — Aloha channel utilization.**  Find the inter-arrival time
that maximizes channel utilization in slotted ALOHA.  The theoretical
maximum is 1/e ≈ 0.368; starting from the overloaded region (0.5 s) the
optimizer converges to iaTime ≈ 1.87 s in about 40 evaluations:

```python
optimize_simulation_parameters(
    get_simulation_task(config_filter="SlottedAloha1", sim_time_limit="10min"),
    expected_result_names=["channelUtilization:last"],
    expected_result_values=[0.368],
    fixed_parameter_names=[], fixed_parameter_values=[],
    fixed_parameter_assignments=[], fixed_parameter_units=[],
    parameter_names=["iaTime"],
    parameter_assignments=["Aloha.host[*].iaTime"],
    parameter_units=["exponential({0}s)"],
    initial_values=[0.5], min_values=[0.1], max_values=[20])
```

```
  ['iaTime'] = [0.5],  ['channelUtilization:last'] = [0.129], diff = [0.239]
  ['iaTime'] = [0.525], ['channelUtilization:last'] = [0.139], diff = [0.229]
  ...
  ['iaTime'] = [1.875], ['channelUtilization:last'] = [0.370], diff = [0.002]
  ...
Best: {'iaTime': 1.873} -> {'channelUtilization:last': 0.367}
Elapsed time: 1.13
```

Note: because `iaTime` is declared as `volatile` in NED with an
`exponential()` distribution in the INI file, the unit format
`"exponential({0}s)"` wraps the numeric value so that the command-line
override preserves the distribution.  Plain units like `"m"` or `"Mbps"`
are appended directly to the value.

**Example 2 — WiFi error rate distance (INET).**  Find the distance at
which 54 Mbps WiFi reaches a 30 % packet error rate.  The optimizer
converges to ≈ 53.2 m in about 28 evaluations:

```python
optimize_simulation_parameters(
    get_simulation_task(simulation_project=inet_project,
        working_directory_filter="showcases/wireless/errorrate",
        config_filter="General", run_number=0, sim_time_limit="1s"),
    expected_result_names=["packetErrorRate:vector"],
    expected_result_values=[0.3],
    fixed_parameter_names=["bitrate"], fixed_parameter_values=[54],
    fixed_parameter_assignments=["**.bitrate"], fixed_parameter_units=["Mbps"],
    parameter_names=["distance"],
    parameter_assignments=["*.destinationHost.mobility.initialX"],
    parameter_units=["m"],
    initial_values=[50], min_values=[20], max_values=[100])
```

```
  ['distance'] = [50.0],  ['packetErrorRate:vector'] = [0.072], diff = [0.228]
  ['distance'] = [52.5],  ['packetErrorRate:vector'] = [0.226], diff = [0.074]
  ...
  ['distance'] = [53.19], ['packetErrorRate:vector'] = [0.300], diff = [0.000]
Best: {'distance': 53.194} -> {'packetErrorRate:vector': 0.300}
Elapsed time: 6.38
```

### Sanitizer tests

Sanitizer tests detect memory errors, undefined behavior, and other
bugs by running simulations with AddressSanitizer / UBSan instrumentation.
Uses the `sanitize` build mode.

```python
run_sanitizer_tests(simulation_project=inet_project)

# Filter to a specific area with a longer time limit
run_sanitizer_tests(simulation_project=inet_project,
                    working_directory_filter="examples/ethernet",
                    cpu_time_limit="10s")
```

### Coverage reports

Coverage reports show which lines of C++ source code are exercised by
simulations.  Uses the `coverage` build mode and LLVM's coverage tools.

```python
# Generate and open a coverage report in the browser
open_coverage_report(simulation_project=inet_project,
                     working_directory_filter="examples/ethernet",
                     sim_time_limit="10s")

# Just generate the report without opening it
generate_coverage_report(simulation_project=inet_project,
                         working_directory_filter="examples/ethernet",
                         sim_time_limit="10s")
```

### Running all tests

```python
# Run every configured test type sequentially
run_all_tests(simulation_project=inet_project)
```

### GitHub Actions integration

Dispatch CI workflows on the project's GitHub repository.  Requires a
personal access token in `~/.ssh/github_repo_token` with `repo` and
`workflow` scopes, and the `github_owner`, `github_repository`, and
`github_workflows` parameters in the project's `.opp` file.

```python
# Dispatch a single workflow
dispatch_workflow("fingerprint-tests.yml")

# Dispatch all configured workflows
dispatch_all_workflows()

# Target a specific project and branch
dispatch_workflow("fingerprint-tests.yml",
                  simulation_project=inet_project, ref="topic/my-feature")
```

### Comparing simulations

Compare simulation results between two projects or two git commits.
The comparison checks stdout trajectories, fingerprint trajectories,
and scalar statistical results.

```python
# Compare two projects
results = compare_simulations(
    simulation_project_1=inet_project,
    simulation_project_2=inet_baseline_project,
    working_directory_filter="examples/ethernet",
    config_filter="General",
    run_number=0)

# Compare two git commits of the same project
results = compare_simulations_between_commits(
    inet_project, "HEAD~1", "HEAD",
    config_filter="General",
    run_number=0)

# Inspect the results
r = results.results[0]
print(r.stdout_trajectory_comparison_result)       # IDENTICAL / DIVERGENT
print(r.fingerprint_trajectory_comparison_result)   # IDENTICAL / DIVERGENT
print(r.statistical_comparison_result)              # IDENTICAL / DIFFERENT
r.print_different_statistical_results(include_relative_errors=True)

# Interactive debugging at the divergence point
r.debug_at_fingerprint_divergence_position()
r.show_divergence_position_in_sequence_chart()
```

### Overlay builds

Overlay builds use `fuse-overlayfs` to create a writable layer on top
of a read-only source tree, allowing out-of-tree builds without
modifying the original checkout.

```python
# Projects with overlay_key in their .opp file use overlays automatically.
# Manage overlays manually:
from opp_repl.simulation.overlay import *

list_overlays()          # list overlay keys under the build root
cleanup_overlays()       # unmount all overlays
clear_build_root()       # unmount and remove all overlay data
```

### SSH cluster execution

Distribute simulation tasks across multiple machines using Dask
(requires the `cluster` extra).

```python
from opp_repl.common.cluster import SSHCluster

cluster = SSHCluster("node1", ["node1", "node2", "node3"])
cluster.start()

# Run simulations on the cluster
run_simulations(simulation_project=inet_project,
                scheduler="cluster")
```

### Loading projects at runtime

```python
load_opp_file("/path/to/project.opp")
load_opp_file("/path/to/workspace/*/*.opp")  # glob patterns supported
```

### Cleaning results

```python
clean_simulation_results(simulation_project=inet_project)
clean_simulation_results(simulation_project=inet_project,
                         working_directory_filter="examples/ethernet")
```

## MCP Server

opp_repl can expose an **MCP (Model Context Protocol) server** that
allows AI assistants to execute Python code in the live REPL session.
Start it with `--mcp-port 9966` (disabled by default).

- **Transport**: Streamable HTTP (stateless), endpoint `http://127.0.0.1:{port}/mcp`
- **Tool**: `execute_python` — runs arbitrary Python code in the IPython session
- **Resources**: `file:///opp_repl/readme` (project README),
  `file:///opp_repl/packages` (package list),
  `file:///opp_repl/api/{package_name}` (auto-generated API reference)

Requires the `mcp` extra: `pip install -e ".[mcp]"`.

## REPL Features

### Autoreload

IPython's `%autoreload 2` magic is enabled at REPL startup so that
edited Python source files are automatically reloaded before each
command.

### User module

At startup the REPL tries to import a Python module named after the
current OS login user (e.g. `import levy`).  All public names from
that module are injected into the REPL namespace.  This allows
per-user customization — define helper functions, set project defaults,
etc. — without modifying opp_repl itself.  If no such module exists, the
import is silently skipped.

### Convenience variables

Every loaded simulation project is injected into the REPL namespace as
`{name}_project` (hyphens and dots replaced by underscores).  For
example, `inet_project`, `simu5g_project`, `aloha_project`.

### stop_execution()

Call `stop_execution()` (or `stop_execution(value)`) anywhere in a
REPL script to abort the current cell without a full traceback.

## License

See the project repository for license information.
