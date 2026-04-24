# Chart Tests

Chart tests detect visual regressions in result analysis charts by
comparing rendered images against saved baseline images.  The baseline
is stored in the `media_folder` of the project.  Requires the `chart`
optional dependency group (matplotlib, numpy).

## Prerequisites

Chart tests require the **`chart`** optional dependency group:

```bash
pip install -e ".[chart]"
```

This installs **matplotlib** and **numpy**.  Without these packages chart
tests are silently skipped by `run_all_tests()` and the `opp_run_chart_tests`
command will fail at import time.

The OMNeT++ **scave** Python module (`omnetpp.scave.analysis`) must also be
available — it is included in any standard OMNeT++ installation.

## How it works

Each chart defined in an `.anf` analysis file that has an
`image_export_filename` property is eligible for testing.  The test
pipeline:

1. Runs the required simulations to produce result files.
2. Exports each chart to a PNG image (150 dpi).
3. Compares the new image against the baseline using the RMSE (root mean
   square error) pixel metric.
4. Reports `PASS` when the metric is exactly 0 (pixel-perfect match) or
   `FAIL` otherwise.

When a test fails, two extra files are written next to the baseline:

- `<name>-new.png` — the newly rendered image
- `<name>-diff.png` — a per-pixel absolute-difference image

## Python API

### Storing baseline charts

Before running chart tests, generate the baseline images:

```python
update_chart_test_results(simulation_project=inet_project)
```

### Running chart tests

```python
r = run_chart_tests(simulation_project=inet_project)

# Filter by working directory
run_chart_tests(simulation_project=inet_project,
                working_directory_filter="showcases")

# Filter by chart name
run_chart_tests(simulation_project=inet_project,
                chart_filter="throughput")
```

### Understanding the test result

`run_chart_tests()` returns a `MultipleTestTaskResults` object.  Each element
in `r.results` is a `TestTaskResult` with:

- **`result`** — `"PASS"`, `"FAIL"`, `"SKIP"`, or `"ERROR"`
- **`reason`** — on `FAIL`, contains the RMSE metric value (e.g. `"Metric: 0.0312"`) or `"Baseline chart not found"`; on `SKIP`, `"Chart file name is not specified"`

```python
r0 = r.results[0]
print(r0.result)   # "PASS" or "FAIL"
print(r0.reason)   # e.g. "Metric: 0.0312"
```

Re-running and filtering works like other test types:

```python
r.get_fail_results().rerun()
```

### Understanding the update result

Each `UpdateTaskResult` carries:

- **`result`** — one of:
  - `"KEEP"` — the new image is pixel-identical to the baseline
  - `"INSERT"` — no baseline existed; the new image becomes the baseline
  - `"UPDATE"` — the baseline was replaced with the new image (the old one is
    saved as `<name>-old.png` and a diff image is generated)
  - `"ERROR"` — the chart was not found in the analysis file

### Filtering options

`get_chart_test_tasks()` and `get_update_chart_tasks()` accept:

- **`working_directory_filter`** — regex on the simulation working directory
- **`chart_filter`** / **`exclude_chart_filter`** — regex on the chart name
- **`run_simulations`** — set to `False` to skip the simulation step (assumes
  result files already exist)

### Comparing against a different baseline

You can test charts against a baseline from a different project (e.g. a
baseline branch):

```python
run_chart_tests(simulation_project=inet_project,
                baseline_simulation_project=inet_baseline_project)
```

## Command Line

```bash
opp_update_chart_test_results --load "/home/user/workspace/inet/inet.opp" -p inet
opp_run_chart_tests --load "/home/user/workspace/inet/inet.opp" -p inet
```
