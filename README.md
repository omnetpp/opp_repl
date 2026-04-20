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
pip install -e ".[all]"    # cluster, chart, optimize, github
pip install -e ".[cluster]" # dask/distributed for SSH clusters
```

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
In [1]: run_simulations(simulation_project=get_simulation_project("fifo"))
```

## Command-Line Options

```
opp_repl [-h]
         [-p PROJECT]              # set default simulation project by name
         [-l {ERROR,WARN,INFO,DEBUG}]  # log level (default: INFO)
         [--external-command-log-level {ERROR,WARN,INFO,DEBUG}]
         [--mcp-port PORT]         # MCP server port, 0 to disable (default: 9966)
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
| `overlay_key` | `str` | `None` | Enable overlay builds with this key |
| `build_root` | `str` | `None` | Override overlay build root |
| `opp_env_workspace` | `str` | `None` | Path to opp_env workspace |
| `opp_env_project` | `str` | `None` | opp_env project identifier (e.g. `"inet-4.6.0"`) |

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
    ini_file_folders=["examples"],
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
run_simulations(simulation_project=get_simulation_project("fifo"))

# Run with a filter and time limit
run_simulations(filter="PureAloha", sim_time_limit="1s")

# Run a specific config
run_simulations(simulation_project=get_simulation_project("aloha"),
                config_filter="PureAlohaExperiment", sim_time_limit="1s")

# Re-run failed simulations
r = run_simulations()
r.get_error_results().rerun()
```

### Building projects

```python
p = get_simulation_project("inet")
build_project(simulation_project=p)
build_project(simulation_project=p, mode="debug")
```

### Smoke tests

```python
run_smoke_tests()
run_smoke_tests(simulation_project=get_simulation_project("aloha"),
                config_filter="PureAlohaExperiment")
```

### Fingerprint tests

```python
# First, store correct fingerprints
update_correct_fingerprints(sim_time_limit="1s")

# Then verify against stored values
run_fingerprint_tests(sim_time_limit="1s")
```

### Loading projects at runtime

```python
load_opp_file("/path/to/project.opp")
load_opp_file("/path/to/workspace/*/*.opp")  # glob patterns supported
```

## License

See the project repository for license information.
