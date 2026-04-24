# Statistical Tests

Statistical tests detect regressions in simulation scalar results by
comparing them against saved baseline values.

## What is compared

Each simulation config is run and its scalar (`.sca`) and vector (`.vec`)
output files are collected.  Vector statistics are extracted into scalar
form using `opp_scavetool`, so the comparison is always scalar-based.
The resulting scalar data is loaded into a pandas DataFrame with columns
`experiment`, `measurement`, `replication`, `module`, `name`, and `value`.

This DataFrame is compared row-by-row against a stored baseline.  The test
detects:

- **Missing or extra rows** — scalars present only in the baseline or only
  in the current run.
- **Changed values** — any scalar whose value differs from the baseline.

When differences are found, a **relative error** is computed for each
changed scalar using an unbounded symmetric formula.  The differences are
sorted by descending absolute relative error, and the worst offender is
shown in the result's `reason` string.

## Baseline storage

Baselines live in the project's `statistics_folder` (default `"."`),
mirroring the working directory structure.  Each baseline is a `.sca` file
named `{ini_file}-{config}-#{run_number}.sca`:

```
<statistics_folder>/
  examples/ethernet/lans/
    omnetpp.ini-MixedLAN-#0.sca
  examples/wireless/handover/
    omnetpp.ini-Handover-#0.sca
```

When a test fails, a `.diff` file and a `.csv` file are written next to the
baseline, making it easy to inspect what changed:

- **`.diff`** — unified diff between baseline and current `.sca` files.
- **`.csv`** — a table of all differing scalars with `value_stored`,
  `value_current`, and `relative_error` columns, sorted by largest error.

## Python API

```python
# Run tests — compares current results against the baseline
run_statistical_tests(simulation_project=inet_project)

# Filter to a specific area
run_statistical_tests(simulation_project=inet_project,
                      working_directory_filter="examples/ethernet")
```

### Filtering scalars

By default every scalar is compared.  You can narrow the comparison using
result-level filters:

```python
# Only compare scalars whose name matches a pattern
run_statistical_tests(result_name_filter="throughput|delay")

# Exclude scalars from specific modules
run_statistical_tests(exclude_result_module_filter=".*scenarioManager.*")
```

### Relative error threshold

Small floating-point differences can be ignored by setting a threshold:

```python
# Tolerate relative errors smaller than 1e-6
run_statistical_tests(relative_error_threshold=1e-6)
```

When all differences fall below the threshold the result is `PASS` with a
reason like `"All differences below relative error threshold 1e-06 (max
relative error 3.2e-07)"`.

## Inspecting results

`run_statistical_tests()` returns a `MultipleSimulationTestTaskResults`.
Each individual result is a `SimulationTestTaskResult`:

```python
r = run_statistical_tests(sim_time_limit="1s")

# Overall status
r.is_all_results_pass()

# Drill into failures
for tr in r.get_fail_results().results:
    print(tr.task.simulation_task.get_parameters_string())
    print(tr.reason)      # worst-offending scalar with stored/current/error
    print(tr.error_message)
```

The `reason` string of a failing test shows the scalar with the largest
relative error, including module path, scalar name, stored value, current
value, and relative error.

To inspect the full set of differences, open the `.csv` file written next
to the baseline:

```python
import pandas as pd
tr = r.get_fail_results().results[0]
cfg = tr.task.simulation_task.simulation_config
proj = cfg.simulation_project
csv_path = proj.get_full_path(
    proj.statistics_folder + "/" + cfg.working_directory + "/" +
    tr.task.get_result_file_name("csv"))
df = pd.read_csv(csv_path)
print(df.sort_values("relative_error", key=abs, ascending=False).head(20))
```

The underlying simulation output is available via
`tr.simulation_task_result` (stdout, stderr, timing, error details — see
[Task results](task_results.md#simulationtaskresult-in-detail)).

## Updating baselines

```python
# Store baseline results (first time, or after intentional changes)
update_statistical_test_results(simulation_project=inet_project)

# Update only a specific area
update_statistical_test_results(simulation_project=inet_project,
                                working_directory_filter="examples/ethernet")
```

The update task runs each simulation, compares against the existing
baseline, and produces `KEEP` (unchanged), `INSERT` (new baseline), or
`UPDATE` (changed baseline).  The new `.sca` file is copied into
`statistics_folder` automatically.

## Command Line

```bash
opp_run_statistical_tests --load "/home/user/workspace/inet/inet.opp" -p inet
opp_update_statistical_test_results --load "/home/user/workspace/inet/inet.opp" -p inet
```
