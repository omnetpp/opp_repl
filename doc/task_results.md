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

Extracts timing, error details, end-of-run position, output file paths,
and used NED types from the simulation’s stdout/stderr.

### Test results

| Class | Produced by | Extra codes |
|---|---|---|
| `TestTaskResult` / `MultipleTestTaskResults` | `TestTask` | `PASS`, `FAIL` |
| `SimulationTestTaskResult` / `MultipleSimulationTestTaskResults` | `SimulationTestTask` | `PASS`, `FAIL` |
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
`MultipleTaskResults`.  This object counts how many runs ended up in each
result category and determines an **overall result** — the worst-case across
all individual outcomes.

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
