# Tasks

A **task** is the central unit of work in opp_repl.  Every operation —
running a simulation, checking a fingerprint, compiling a source file,
comparing two runs — is modelled as a task object that captures all
necessary parameters so that it can be executed, re-run, or dispatched to
a cluster without any extra context.

## Base classes

The task framework lives in `opp_repl.common.task` and provides two
foundational pairs:

- **`Task`** / **`TaskResult`** — a single self-contained operation and
  its outcome.  `Task.run()` handles timing, progress reporting,
  exception handling, and keyboard interrupt support; subclasses only
  override `run_protected()` to do the actual work.
- **`MultipleTasks`** / **`MultipleTaskResults`** — a collection of tasks
  that can be executed sequentially or concurrently (via threads,
  processes, or a Dask cluster).  The aggregate result summarises counts
  per result code and determines the overall worst-case outcome.

Every task produces a result with a **result code** (e.g. `DONE`, `ERROR`,
`CANCEL`) and an **expected result** (usually `DONE`).  When the two
differ, the result is flagged as **unexpected**.

All task and result objects support `recreate()` (create a modified copy)
and `rerun()` (re-execute with the same or modified parameters).

## Task classification

The base classes are specialised into several families:

### Simulation tasks

| Class | Purpose |
|---|---|
| `SimulationTask` | Run a single simulation (subprocess, in-process, or IDE debugger) |
| `MultipleSimulationTasks` | Run many simulation tasks, with optional build step |

These are the most common tasks.  A `SimulationTask` carries a
`SimulationConfig`, run number, build mode, time limits, and output path
overrides.  Result codes: `DONE`, `SKIP`, `CANCEL`, `ERROR`.

### Test tasks

Test tasks wrap a simulation run and add a verification step.  Their
result codes include `PASS` and `FAIL` in addition to the standard set.

| Class | Purpose |
|---|---|
| `TestTask` / `MultipleTestTasks` | Abstract base for all tests |
| `SimulationTestTask` / `MultipleSimulationTestTasks` | Test that wraps a `SimulationTask` |
| `FingerprintTestTask` / `FingerprintTestGroupTask` | Check simulation fingerprints against stored baselines |
| `SpeedTestTask` | Check that instruction count stays within tolerance of a baseline |
| `StatisticalTestTask` | Compare scalar results against stored baselines |
| `ChartTestTask` / `MultipleChartTestTasks` | Compare chart images against stored baselines |
| `SmokeTestTask` | Simple smoke test — verify the simulation starts and finishes |

### Update tasks

Update tasks re-run simulations and update the stored baselines when
results change.  Their result codes are `KEEP` (baseline unchanged),
`INSERT`, `UPDATE`, `SKIP`, `CANCEL`, `ERROR`.

| Class | Purpose |
|---|---|
| `UpdateTask` / `MultipleUpdateTasks` | Abstract base for all updates |
| `SimulationUpdateTask` / `MultipleSimulationUpdateTasks` | Update that wraps a `SimulationTask` |
| `FingerprintUpdateTask` | Update the fingerprint store |
| `SpeedUpdateTask` / `MultipleSpeedUpdateTasks` | Update the speed measurement store |
| `StatisticalResultsUpdateTask` | Update stored scalar baselines |
| `ChartUpdateTask` / `MultipleChartUpdateTasks` | Update stored chart images |

### Build tasks

Build tasks compile source files.  They include an `is_up_to_date()` check
that skips compilation when outputs are newer than inputs.

| Class | Purpose |
|---|---|
| `BuildTask` | Abstract base for compilation steps |
| `MsgCompileTask` | Compile a `.msg` file |
| `CppCompileTask` | Compile a `.cc` file |
| `LinkTask` | Link object files into an executable or shared library |
| `CopyBinaryTask` | Copy built binaries to the project's bin/library folder |
| `BuildSimulationProjectTask` | Orchestrate a full project build (MSG → C++ → link → copy) |

### Comparison tasks

Comparison tasks run the same simulation config against two project
variants and analyse the differences.

| Class | Purpose |
|---|---|
| `CompareSimulationsTask` | Compare stdout trajectories, fingerprint trajectories, and scalar results |
| `MultipleCompareSimulationsTaskResults` | Aggregate comparison results; codes include `IDENTICAL`, `DIVERGENT`, `DIFFERENT` |

## Simulation tasks in detail

### From configs to tasks

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

### What a task knows

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

### Build modes

The `mode` parameter selects which build of the simulation binary to use:

| Mode | Suffix | Use case |
|---|---|---|
| `release` | `_release` | Optimized builds (default) |
| `debug` | `_dbg` | Stepping through code |
| `sanitize` | `_sanitize` | AddressSanitizer / UBSan |
| `coverage` | `_coverage` | Code coverage |
| `profile` | `_profile` | Performance profiling |

### Simulation runners

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

### Running multiple tasks

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

### Re-running and recreating

Both individual tasks and multiple-task objects support `rerun()` and
`recreate()`.  Calling `rerun()` without arguments repeats the previous run
with the same settings; passing keyword arguments creates a modified copy
first:

```python
task.rerun()                          # identical re-run
task.rerun(mode="debug")              # re-run in debug mode (creates a new task)
mt.rerun(concurrent=False)            # re-run all tasks sequentially
```

### Hashing and caching

Each task computes a SHA-256 hash over the project state, config, run
number, mode, and time limit.  This hash can be used by higher-level tools
to detect when a re-run is necessary because something has changed.

### Housekeeping

- `clean_simulation_results()` removes `.sca`, `.vec`, `.vci`, `.elog`,
  `.log`, `.rt` files from the result folders of all matching configs.
- Individual tasks also expose `clear_result_folder()` and
  `remove_result_folder()` for finer-grained cleanup.
