# Simulation Configs

A `SimulationConfig` represents a single **`[Config ...]` section** from
one INI file within a simulation project.  Configs are the bridge between
the project's INI files and the simulation tasks that opp_repl creates and
runs.

## How configs are discovered

When you call `get_simulation_configs()` on a project (or any function that
needs them, like `run_simulations()`), opp_repl scans the project's
`ini_file_folders` recursively for `*.ini` files.  Each INI file is parsed
to extract all `[Config ...]` sections and the `[General]` section.  The
results are cached so subsequent calls are fast.  The cache is
automatically invalidated when any `.ini` file in the project's
`ini_file_folders` is modified, so changes are picked up without a
restart.

If the project produces a dynamic library, it is built automatically
before config discovery so that `opp_run -q numruns` can load the
required modules.

For each section the parser extracts:

- **`working_directory`** — the folder containing the INI file, relative to
  the project root.
- **`ini_file`** — the INI file name (e.g. `omnetpp.ini`).
- **`config`** — the section name (e.g. `"General"`,
  `"PureAlohaExperiment"`).
- **`num_runs`** — the total number of runs, determined from iteration
  variables and `repeat=N`.
- **`sim_time_limit`** — the simulation time limit, if specified.
- **`abstract`** — whether the config is meant to be extended, not run
  directly.  Detected from an `abstract = true` annotation, a
  `(Abstract)` tag in the description, or the absence of a `network`
  setting in the `[General]` section.
- **`emulation`** — whether the config requires external emulation
  resources.  Also auto-detected if the working directory contains
  `"emulation"`.
- **`expected_result`** — the expected outcome (`"DONE"` by default; can be
  overridden with `expected-result = "ERROR"` in a comment).
- **`description`** — the human-readable `description` from the INI file.

## Filtering configs

Most functions that operate on configs accept **regex-based include/exclude
filter pairs** to narrow the selection.  A config is included only when all
specified filters match:

| Include filter | Exclude filter | Matches against |
|---|---|---|
| `filter` | `exclude_filter` | full config string representation |
| `working_directory_filter` | `exclude_working_directory_filter` | working directory path |
| `ini_file_filter` | `exclude_ini_file_filter` | INI file name |
| `config_filter` | `exclude_config_filter` | config section name |

In addition, `simulation_config_filter` accepts a **predicate function**
that receives each config and returns `True` or `False`.  By default it
excludes abstract and emulation configs.

Setting `full_match=True` requires the regex to match the entire string
rather than just a substring.

Example:

```python
# Only configs under examples/ethernet whose name contains "Vlan"
configs = p.get_simulation_configs(
    working_directory_filter="examples/ethernet",
    config_filter="Vlan"
)
```

## From configs to tasks

Each config expands into one or more simulation tasks — one per run number.
The `get_simulation_tasks()` function performs this expansion and applies
additional run-number filtering.  See [Simulation tasks](tasks.md) for details.

## Number of runs

The number of runs is determined from iteration variables (e.g.
`${x=1,2,3}`) and `repeat=N` in the INI file.  opp_repl first tries to
parse the INI file with OMNeT++'s Python bindings; if that fails (e.g.
because the config uses a custom `configuration-class`), it falls back to
running `opp_run -q numruns` as a subprocess.

## Cleaning results

Each config knows how to clean its result files:

```python
config.clean_simulation_results()
```

This removes the entire `results/` directory under the config's working
directory.  The project-level `clean_simulation_results()` function applies
this to all matching configs at once.
