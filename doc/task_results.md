# Task Results

Every task execution produces a **result object** that captures the
outcome.  The result framework mirrors the task hierarchy: there is a
base `TaskResult` / `MultipleTaskResults` pair, and each task family has
its own specialised result classes.

## Base classes

- **`TaskResult`** — produced by a single `Task`.  Stores the result
  code, expected result, reason string, error message, wall-clock time,
  and optional project-state hashes.  Supports `recreate()` (modified
  copy) and `rerun()` (re-execute the originating task).
- **`MultipleTaskResults`** — produced by `MultipleTasks`.  Counts results
  per code (expected vs. unexpected), determines the overall worst-case
  result, and provides filtering and drill-down methods.

## Result classification

### Simulation results

| Class | Produced by | Result codes |
|---|---|---|
| `SimulationTaskResult` | `SimulationTask` | `DONE`, `SKIP`, `CANCEL`, `ERROR` |
| `MultipleSimulationTaskResults` | `MultipleSimulationTasks` | same |

Extracts timing, error details, end-of-run position, output file paths,
and used NED types from the simulation's stdout/stderr.

### Test results

| Class | Produced by | Extra codes |
|---|---|---|
| `TestTaskResult` / `MultipleTestTaskResults` | `TestTask` | `PASS`, `FAIL` |
| `SimulationTestTaskResult` / `MultipleSimulationTestTaskResults` | `SimulationTestTask` | `PASS`, `FAIL` |
| `StatisticalTestTaskResult` / `MultipleStatisticalTestTaskResults` | `StatisticalTestTask` | `PASS`, `FAIL` |
| `SpeedTestTaskResult` | `SpeedTestTask` | `PASS`, `FAIL` |
| `ChartTestTaskResult` | `ChartTestTask` | `PASS`, `FAIL` |
| `FingerprintTestTaskResult` / `MultipleFingerprintTestTaskResults` | `FingerprintTestTask` | `PASS`, `FAIL` |
| `SpeedUpdateTaskResult` | `SpeedUpdateTask` | `KEEP`, `INSERT`, `UPDATE` |

Test results carry the underlying `SimulationTaskResult` so you can
inspect both the test verdict and the raw simulation output.

### Update results

| Class | Produced by | Result codes |
|---|---|---|
| `UpdateTaskResult` / `MultipleUpdateTaskResults` | `UpdateTask` | `KEEP`, `INSERT`, `UPDATE`, `SKIP`, `CANCEL`, `ERROR` |
| `SimulationUpdateTaskResult` | `SimulationUpdateTask` | same |
| `FingerprintUpdateTaskResult` / `MultipleFingerprintUpdateTaskResults` | `FingerprintUpdateTask` | same |
| `SpeedUpdateTaskResult` | `SpeedUpdateTask` | same |

`KEEP` means the baseline is unchanged; `INSERT` and `UPDATE` mean a new
or changed baseline was written.

### Build results

| Class | Produced by | Result codes |
|---|---|---|
| `BuildTaskResult` / `MultipleBuildTaskResults` | `BuildTask` and subclasses | `DONE`, `SKIP`, `CANCEL`, `ERROR` |

`SKIP` means the build was up-to-date and no compilation was needed.

### Comparison results

| Class | Produced by | Result codes |
|---|---|---|
| `CompareSimulationsTaskResult` | `CompareSimulationsTask` | `IDENTICAL`, `DIVERGENT`, `DIFFERENT`, `SKIP`, `CANCEL`, `ERROR` |
| `MultipleCompareSimulationsTaskResults` | multiple comparisons | same |

Comparison results include detailed sub-verdicts for stdout trajectories,
fingerprint trajectories, and scalar statistics, plus methods for
debugging at the divergence point.

## Standard result codes

The default result codes used by simulation tasks:

| Code | Meaning |
|---|---|
| `DONE` | The simulation completed successfully (exit code 0). |
| `SKIP` | The simulation was skipped — typically because it prompts for user input, which is not possible in batch mode. |
| `CANCEL` | The run was cancelled, usually by pressing Ctrl-C. |
| `ERROR` | The simulation failed with a non-zero exit code or an unhandled exception. |

Every result also carries an **expected result** (defaulting to `DONE`).
When the actual outcome differs from the expectation the result is flagged
as **unexpected**, which makes it easy to spot regressions in large test
runs.

## SimulationTaskResult in detail

A `SimulationTaskResult` holds a reference back to the task that created it,
plus information extracted from the simulation's output:

- **Timing** — wall-clock time is always recorded.  If the simulation
  prints its CPU usage summary, CPU time, cycle count, and instruction
  count are captured as well.
- **Error details** — when the simulation reports an error, the result
  parses out the error message, the module path where it occurred, and the
  simulation time and event number at the point of failure.
- **End-of-run position** — the last event number and simulation time
  reached before the run ended (from the time-limit-reached message).
- **Output file paths** — the relative paths to the stdout, eventlog,
  scalar (`.sca`), and vector (`.vec`) files that the run produced.
- **Used NED types** — a sorted list of all NED types that were
  instantiated, useful for dependency analysis.
- **Subprocess result** — the raw `CompletedProcess` object is available
  for low-level inspection of return code, stdout, and stderr.

### Accessing stdout and stderr

The captured process output is available directly on the result:

```python
r = run_simulations(config_filter="Aloha", sim_time_limit="1s")
tr = r.results[0]

# Captured output as strings
tr.stdout                    # simulation's stdout (captured by the subprocess runner)
tr.stderr                    # simulation's stderr

# The raw subprocess.CompletedProcess object
tr.subprocess_result.returncode
tr.subprocess_result.stdout  # same as tr.stdout
tr.subprocess_result.stderr  # same as tr.stderr
```

When simulations run with `Cmdenv`, stdout is also written to a file.  The
relative path is available as `stdout_file_path`:

```python
tr.stdout_file_path          # e.g. "results/PureAloha-#0.out"
```

### Accessing output files

Each `SimulationTaskResult` records the relative paths (relative to the
simulation's working directory) for the output files the run produced:

```python
tr.stdout_file_path          # e.g. "results/PureAloha-#0.out"
tr.eventlog_file_path        # e.g. "results/PureAloha-#0.elog"
tr.scalar_file_path          # e.g. "results/PureAloha-#0.sca"
tr.vector_file_path          # e.g. "results/PureAloha-#0.vec"
```

These paths are relative to the simulation config's working directory.  To
get an absolute path, combine them with the project's `get_full_path()`:

```python
project = tr.task.simulation_config.simulation_project
workdir = tr.task.simulation_config.working_directory
abs_path = project.get_full_path(workdir + "/" + tr.scalar_file_path)
```

The eventlog file (`.elog`) is only produced when eventlog recording is
enabled (pass `record_eventlog=True` to `run_simulations()`).

### Error attributes

When a simulation reports an error, `SimulationTaskResult` parses the
error message and exposes structured fields:

```python
tr = r.results[0]
tr.error_message            # e.g. "Cannot route: no interface for next hop"
tr.error_module             # e.g. "(inet::Ipv4) host.ipv4.ip"
tr.error_simulation_time    # e.g. "1.234"
tr.error_event_number       # e.g. 5821
```

These are `None` when the simulation completed without error or when the
error output could not be parsed.

### Reading simulation results

`SimulationTaskResult` provides convenience methods for reading the
scalar, vector, and histogram result files produced by the simulation.
These return pandas DataFrames using `omnetpp.scave.results` internally.

```python
r = run_simulations(config_filter="Aloha", sim_time_limit="100s")
tr = r.results[0]

# Scalars (from the .sca file)
df = tr.get_scalars()                      # all scalars, including statistic fields
df = tr.get_scalars(include_fields=False)   # only explicitly recorded scalars
df = tr.get_scalars(include_runattrs=True)  # include run attributes as extra columns

# Vectors (from the .vec file)
df = tr.get_vectors()

# Histograms (from the .sca file)
df = tr.get_histograms()
```

When working with multiple runs, `MultipleSimulationTaskResults` provides
the same methods, merging all individual `DONE` results into a single
DataFrame:

```python
r = run_simulations(config_filter="Aloha", sim_time_limit="100s")

# Merged scalars from all successful runs
df = r.get_scalars()

# Merged vectors / histograms
df = r.get_vectors()
df = r.get_histograms()
```

### Navigating from a result to its task and config

Every result holds a reference to the task that created it.  From the task
you can reach the simulation config and project:

```python
tr = r.results[0]

# The task
tr.task                                  # SimulationTask
tr.task.run_number                       # 0
tr.task.mode                             # "release"
tr.task.sim_time_limit                   # "1s"

# The config
cfg = tr.task.simulation_config
cfg.working_directory                    # "examples/ethernet/lans"
cfg.ini_file                             # "omnetpp.ini"
cfg.config                               # "MixedLAN"

# The project
proj = cfg.simulation_project
proj.name                                # "inet"
proj.get_full_path(cfg.working_directory)  # absolute path
```

For test and update results, the underlying simulation result is available
as `tr.simulation_task_result`, which provides the same navigation plus
the simulation-specific attributes (output files, timing, errors).

## Test result details

### FingerprintTestTaskResult

Extends `SimulationTestTaskResult` with fingerprint-specific fields:

```python
tr.expected_fingerprint      # Fingerprint("a82f-d3c1", "tplx")
tr.calculated_fingerprint    # Fingerprint("b91e-c2a0", "tplx")
tr.fingerprint_mismatch      # True if they differ
tr.simulation_task_result    # the underlying SimulationTaskResult
```

### StatisticalTestTaskResult

Extends `SimulationTestTaskResult` with stored DataFrames for post-run
re-filtering:

```python
tr.stored_df       # baseline scalar DataFrame (or None)
tr.current_df      # current scalar DataFrame
tr.comparison      # ScalarComparisonResult (or None)
```

The `recheck()` method returns a **new** result with the comparison
recomputed under different filters:

```python
tr2 = tr.recheck(exclude_name_filter="jitter")
tr3 = tr.recheck(name_filter="throughput", module_filter=".*router.*")
print(tr2.result)   # "PASS" or "FAIL"
```

The `MultipleStatisticalTestTaskResults` wrapper also supports bulk
`recheck()` which returns a new results object with all verdicts
recomputed.

See [Statistical tests — Re-filtering](statistical_tests.md#re-filtering-results-after-a-run).

### SpeedTestTaskResult

Extends `SimulationTestTaskResult` with stored instruction counts for
post-run re-evaluation with a different tolerance:

```python
tr.num_cpu_instructions           # measured during this run
tr.expected_num_cpu_instructions  # from the speed store baseline
```

The `recheck()` method returns a **new** result with a different tolerance:

```python
tr2 = tr.recheck(max_relative_error=0.15)  # allow 15% instead of 10%
print(tr2.result)   # "PASS" or "FAIL"
```

### ChartTestTaskResult

Extends `TestTaskResult` with the stored image comparison metric:

```python
tr.metric   # RMSE between baseline and current chart (float or None)
```

The `recheck()` method returns a **new** result with a different threshold:

```python
tr2 = tr.recheck(metric_threshold=0.01)  # tolerate small differences
print(tr2.result)   # "PASS" or "FAIL"
```

### SpeedUpdateTaskResult

Carries instruction counts for the speed update comparison:

```python
tr.expected_num_cpu_instructions  # from the speed store baseline
tr.num_cpu_instructions           # measured during this run
```

The result is `KEEP` when within tolerance, `INSERT` when no baseline
existed, and `UPDATE` when the difference exceeds the threshold (default
10%).

### FingerprintUpdateTaskResult

```python
tr.correct_fingerprint       # from the store (None if new entry)
tr.calculated_fingerprint    # computed during this run
```

Result is `KEEP` when unchanged, `INSERT` when no prior entry existed,
`UPDATE` when the fingerprint changed.

## Inspecting results

The result can print a colored one-line summary via `print_result()`, or you
can retrieve the description as a string with `get_description()`.  For
deeper inspection, `print_stdout()` and `print_stderr()` dump the captured
output line by line.

For post-mortem analysis of specific runs, two trajectory methods are
available:

- `get_fingerprint_trajectory()` reads the eventlog and returns a
  `FingerprintTrajectory` — a sequence of per-event fingerprint values
  useful for bisecting where two runs diverge.
- `get_stdout_trajectory()` reads the stdout file and returns a
  `StdoutTrajectory` — event numbers paired with matching output lines,
  optionally filtered by regex.

## Working with multiple results

`run_simulations()` and `MultipleSimulationTasks.run()` return a
`MultipleSimulationTaskResults`.  This object counts how many runs ended up
in each result category and determines an **overall result** — the worst-case
across all individual outcomes.  It also provides `get_scalars()`,
`get_vectors()`, and `get_histograms()` for reading merged result data
(see *Reading simulation results* above).

A typical workflow after a large run:

```python
r = run_simulations(sim_time_limit="1s")

# Quick overview
r                           # prints summary + unexpected details

# Drill down
r.get_error_results()       # only ERROR results
r.get_unexpected_results()  # anything unexpected (excludes SKIP/CANCEL)
r.get_done_results()        # only DONE results

# Check overall status
r.is_all_results_done()     # True if every result is expected DONE
r.is_all_results_expected() # True if every result matches its expectation
```

The `filter_results()` method offers full control — you can filter by result
code, expected result, error message regex, or any combination.  Every
filter method returns a new `MultipleTaskResults`, so filters can be
chained.

## Re-running from results

Both single and multiple results support `rerun()`.  This re-executes the
original task(s) with the same parameters:

```python
r = run_simulations(sim_time_limit="1s")

# Re-run everything
r.rerun()

# Re-run only the failures
r.get_error_results().rerun()

# Re-run a single result in debug mode
r.results[0].rerun(mode="debug")
```

## Hashing

Each result can optionally store hash digests of the project state that
produced it (complete or partial, binary or source).  Higher-level tools
such as fingerprint tests use these hashes to detect whether a cached result
is still valid or whether the underlying code has changed and a re-run is
needed.
