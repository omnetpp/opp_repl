# Comparing Simulations

Compare simulation results between two projects or two git commits.
The comparison checks three aspects of each simulation run: stdout
trajectories, fingerprint trajectories, and scalar statistical results.

## Python API

### Running a comparison

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
```

Both functions accept the same filter parameters as `run_simulations()` (e.g.
`working_directory_filter`, `config_filter`, `run_number`).

### Disabling individual comparison axes

By default the comparison checks stdout trajectories, fingerprint trajectories,
and scalar statistics.  Each axis can be disabled independently:

- **`compare_stdout`** (bool) — compare stdout trajectories (default `True`)
- **`compare_fingerprint`** (bool) — compare fingerprint trajectories (default `True`)
- **`compare_statistics`** (bool) — compare scalar statistical results (default `True`)

```python
# Only compare statistics, skip stdout and fingerprint trajectories
results = compare_simulations(
    simulation_project_1=inet_project,
    simulation_project_2=inet_baseline_project,
    compare_stdout=False,
    compare_fingerprint=False,
    working_directory_filter="examples/ethernet",
    config_filter="General",
    run_number=0)

# Same flags work with git-based comparison
results = compare_simulations_between_commits(
    inet_project, "HEAD~1", "HEAD",
    compare_statistics=False,
    config_filter="General",
    run_number=0)
```

The flags are stored on the `CompareSimulationsTask`, so they are honoured when
the task is re-run.

Additional keyword arguments can narrow the statistical and stdout comparison:

- **`statistical_result_name_filter`** / **`exclude_statistic_name_filter`** — filter scalar names
- **`statistical_result_module_filter`** / **`exclude_statistic_module_filter`** — filter module paths
- **`stdout_filter`** / **`exclude_stdout_filter`** — filter stdout lines before comparing

### Understanding the result

`compare_simulations()` returns a `MultipleCompareSimulationsTaskResults`
object.  It aggregates individual comparison results — one per matching
simulation config — in its `results` list.  Printing it shows the overall
verdict and a summary of any unexpected differences:

```python
print(results)
# Multiple simulation comparison results: IDENTICAL, summary: 3 IDENTICAL, ...
```

Each element in `results.results` is a `CompareSimulationsTaskResult` with:

- **`result`** — overall verdict: `"IDENTICAL"`, `"DIVERGENT"`, or `"DIFFERENT"`
- **`reason`** — human-readable explanation (e.g. `"different fingerprint trajectories, different statistics"`) or `None` when identical
- **`expected`** — `True` when the result is `"IDENTICAL"`

The individual result also carries the three per-axis sub-results described
below.

### Stdout trajectory comparison

The stdout trajectory records every line printed to standard output, tagged
with the event number that produced it.  The two trajectories are compared
line-by-line.

```python
r = results.results[0]
r.stdout_trajectory_comparison_result   # "IDENTICAL" or "DIVERGENT"
```

When divergent, `stdout_trajectory_divergence_position` points to the first
line that differs.  You can inspect it and drill down:

```python
r.stdout_trajectory_divergence_position                  # divergence position object (or None)
r.stdout_trajectory_divergence_position.get_description() # event number, simulation time, module, message
```

### Fingerprint trajectory comparison

The fingerprint trajectory is a cumulative hash recorded at every simulation
event.  When two runs first produce a different fingerprint the *preceding*
event is the one that behaved differently.

```python
r.fingerprint_trajectory_comparison_result   # "IDENTICAL" or "DIVERGENT"
```

When divergent:

```python
r.fingerprint_trajectory_divergence_position                  # divergence position object (or None)
r.fingerprint_trajectory_divergence_position.get_description() # event details for both sides
```

You can walk up the causal chain to understand *why* the divergence occurred:

```python
r.print_divergence_position_cause_chain()             # prints 3 cause events by default
r.print_divergence_position_cause_chain(num_cause_events=5)  # walk further back
```

### Statistical (scalar) result comparison

Scalar results (`.sca` files, plus statistics extracted from `.vec` files) are
loaded into DataFrames and compared by `(experiment, measurement, replication,
module, name)`.  Values that differ, or that exist on only one side, are
collected into `different_statistical_results`.

```python
r.statistical_comparison_result   # "IDENTICAL" or "DIFFERENT"
```

When different, several attributes and methods help you drill down:

```python
r.different_statistical_results   # pandas DataFrame sorted by relative_error (descending)
r.identical_statistical_results   # DataFrame of scalars that match exactly
r.df_1, r.df_2                    # the raw scalar DataFrames for the two sides

# Print helpers
r.print_different_statistic_modules()                          # list affected modules
r.print_different_statistic_names()                            # list affected scalar names
r.print_different_statistical_results()                        # compact table
r.print_different_statistical_results(include_relative_errors=True)   # add relative error column
r.print_different_statistical_results(include_absolute_errors=True)   # add absolute error column
r.print_different_statistical_results(include_relative_errors=True,
                                      include_absolute_errors=True)   # both error columns
```

The `different_statistical_results` DataFrame contains columns `module`,
`name`, `value_1`, `value_2`, `absolute_error`, and `relative_error`, so you
can also filter it directly with standard pandas operations:

```python
df = r.different_statistical_results
df[df["relative_error"] > 0.01]          # only differences above 1 %
df[df["module"].str.contains("router")]  # only router modules
```

### Re-filtering the comparison

Running the comparison is expensive because it involves running two
simulations.  Once you have the results, you can re-apply different
filters and recompute the verdict without re-running anything.
`recompare()` returns a **new** result object; the original is unchanged.

```python
# Re-run with different stdout and statistics filters
r2 = r.recompare(
    exclude_stdout_filter=".*DEBUG.*",
    exclude_statistic_name_filter="jitter",
    statistical_result_module_filter=".*router.*")

r2.stdout_trajectory_comparison_result   # "IDENTICAL" or "DIVERGENT"
r2.statistical_comparison_result         # "IDENTICAL" or "DIFFERENT"
r2.result                                # overall verdict is recomputed
```

`recompare()` accepts the following keyword arguments:

- **Stdout filters**: `stdout_filter`, `exclude_stdout_filter`
- **Statistics filters**: `statistical_result_name_filter`,
  `exclude_statistic_name_filter`, `statistical_result_module_filter`,
  `exclude_statistic_module_filter`, `full_match`

### Interactive debugging and visualization

Once you have identified a divergence, you can launch interactive debugging
sessions or visualize the divergence point:

```python
# Launch two debugger sessions stopped at the divergence event
r.debug_at_fingerprint_divergence_position()
r.debug_at_stdout_divergence_position()

# Open two Qtenv instances fast-forwarded to the divergence event
r.run_until_fingerprint_divergence_position()
r.run_until_stdout_divergence_position()

# Open the eventlog files in the sequence chart at the divergence event
r.show_divergence_position_in_sequence_chart()
```

The `num_cause_events` parameter lets you step back along the causal chain
before stopping.  For example, to break at the event that *caused* the
divergent event:

```python
r.debug_at_fingerprint_divergence_position(num_cause_events=1)
r.run_until_fingerprint_divergence_position(num_cause_events=1)
```
