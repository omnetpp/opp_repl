# Simulation Tasks

A simulation task is the central unit of work in opp_repl.  It captures
everything needed to execute a single simulation run — the config, the run
number, the build mode, time limits, output paths — so that the run can be
launched, stored, re-run, or handed off to a cluster without any extra
context.

## From configs to tasks

Every `SimulationConfig` discovered in a project may expand into one or more
tasks (one per run number).  The function `get_simulation_tasks()` performs
this expansion and returns a `MultipleSimulationTasks` object ready to be
run:

```python
mt = get_simulation_tasks(config_filter="PureAloha", sim_time_limit="1s")
mt.run()
```

A shorthand combines both steps:

```python
run_simulations(config_filter="PureAloha", sim_time_limit="1s")
```

If you need exactly one task — for example to inspect it or debug it — use
`get_simulation_task()`, which raises an error when the filters don't match
exactly one run.

All the config-level filters described in [concepts.md](concepts.md#filtering)
(`working_directory_filter`, `config_filter`, etc.) are accepted here, plus
`run_number`, `run_number_filter` and `exclude_run_number_filter` to narrow
down specific run numbers.

## What a task knows

A `SimulationTask` carries the simulation config it belongs to, the run
number, the build mode, and a set of optional overrides:

- **Time limits** — `sim_time_limit` and `cpu_time_limit` override whatever
  the INI file says.  Both accept a plain string (`"10s"`) or a callable
  `(config, run_number) → string` for per-run limits.
- **Result files** — by default output goes to the `results/` folder with
  names derived from the config and run number.  The paths for stdout,
  eventlog, scalar, and vector files can each be overridden individually.
- **Recording options** — `record_eventlog` and `record_pcap` toggle
  eventlog and PCAP recording.
- **User interface** — `"Cmdenv"` (default) or `"Qtenv"`.
- **Extra INI entries** — `inifile_entries` is a list of additional entries
  passed on the command line as `--<entry>`.

## Build modes

The `mode` parameter selects which build of the simulation binary to use:

| Mode | Suffix | Use case |
|---|---|---|
| `release` | `_release` | Optimized builds (default) |
| `debug` | `_dbg` | Stepping through code |
| `sanitize` | `_sanitize` | AddressSanitizer / UBSan |
| `coverage` | `_coverage` | Code coverage |
| `profile` | `_profile` | Performance profiling |

## Simulation runners

When a task is run, the actual execution is delegated to a **runner**.  The
runner is chosen automatically but can be overridden with the
`simulation_runner` parameter:

- **`subprocess`** (default) — launches the simulation as a child process.
- **`opp_env`** — routes through `opp_env run`; selected automatically when
  the project has an `opp_env_workspace`.
- **`inprocess`** — runs inside the Python process via CFFI.
- **`ide`** — attaches the IDE debugger; selected automatically when
  `debug=True`.

Setting `debug=True` (or passing `break_at_event_number` /
`break_at_matching_event`) switches the mode to `debug` and the runner to
`ide` automatically.

## Running multiple tasks

`MultipleSimulationTasks` wraps a list of tasks and manages their execution.
By default tasks run **concurrently** using all CPU cores, but this can be
controlled:

- `concurrent=False` — sequential execution.
- `scheduler` — `"thread"` (default), `"process"` (multiprocessing), or
  `"cluster"` (Dask distributed).
- `randomize=True` — shuffles execution order.
- `build=True` — builds the project before the first task (enabled by
  default).

Pressing **Ctrl-C** during execution cancels the remaining tasks; results
collected so far are still available in the returned object.

## Re-running and recreating

Both individual tasks and multiple-task objects support `rerun()` and
`recreate()`.  Calling `rerun()` without arguments repeats the previous run
with the same settings; passing keyword arguments creates a modified copy
first:

```python
task.rerun()                          # identical re-run
task.rerun(mode="debug")              # re-run in debug mode (creates a new task)
mt.rerun(concurrent=False)            # re-run all tasks sequentially
```

## Hashing and caching

Each task computes a SHA-256 hash over the project state, config, run
number, mode, and time limit.  This hash can be used by higher-level tools
to detect when a re-run is necessary because something has changed.

## Housekeeping

- `clean_simulation_results()` removes `.sca`, `.vec`, `.vci`, `.elog`,
  `.log`, `.rt` files from the result folders of all matching configs.
- Individual tasks also expose `clear_result_folder()` and
  `remove_result_folder()` for finer-grained cleanup.
