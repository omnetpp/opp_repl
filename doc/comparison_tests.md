# Comparison Tests

Comparison tests detect regressions by running the
[simulation comparison](comparing_simulations.md) pipeline and reporting a
`PASS` / `FAIL` / `ERROR` verdict.

This is closely related to, but distinct from, the `compare_*` API:

| Use case | Function family | Verdicts | Output |
| --- | --- | --- | --- |
| Investigate **why** runs differ | `compare_*` | `IDENTICAL` / `DIVERGENT` / `DIFFERENT` | rich — divergence positions, cause chains, statistic diff tables |
| Detect regressions | `run_*_comparison_tests` | `PASS` / `FAIL` / `ERROR` | counts (`num_pass`, `num_fail`, …) |

Unlike [fingerprint tests](fingerprint_tests.md) and
[statistical tests](statistical_tests.md), comparison tests do not consult a
stored baseline.  Instead they compare runs of two arbitrary versions —
useful for detecting regressions on a development branch without updating
any stored baseline.

## Python API

### Comparing two projects

```python
r = run_simulation_comparison_tests(
    simulation_project_1=inet_project,
    simulation_project_2=inet_baseline_project,
    working_directory_filter="examples/ethernet",
    config_filter="General",
    run_number=0)
```

Each per-config result is `PASS` if the two runs are identical, `FAIL` if
they differ, `ERROR` if either run failed.

### Comparing two git commits

```python
r = run_simulation_comparison_tests_between_commits(
    inet_project, git_hash_1="HEAD~1", git_hash_2="HEAD",
    config_filter="General",
    run_number=0)
```

### Comparing across a sequence of commits

`run_simulation_comparison_tests_across_commits` walks a longer stretch
of history.  Per-pair `PASS` means the candidate commit compares without
regression to its reference; the `comparison_mode` parameter decides what
the reference is:

- **`comparison_mode="differential"`** (default) — each commit vs. its
  predecessor.  Useful for pinpointing the commit that introduced a
  regression on a development branch.
- **`comparison_mode="baseline"`** — each commit vs. the first one.
  Useful for detecting cumulative drift from a reference point.

```python
# Walk the last five commits, one step at a time
r = run_simulation_comparison_tests_across_commits(
    inet_project,
    commits="HEAD~5..HEAD",
    comparison_mode="differential",
    config_filter="General",
    run_number=0)

# Compare every release tag against v4.5.0
r = run_simulation_comparison_tests_across_commits(
    inet_project,
    commits=["v4.5.0", "v4.5.1", "v4.5.2", "HEAD"],
    comparison_mode="baseline",
    config_filter="General",
    run_number=0)
```

The same `commits` / `comparison_mode` semantics as
[`compare_simulations_across_commits`](comparing_simulations.md#comparing-across-a-sequence-of-commits)
apply.  `delete_worktree=True` likewise removes the worktrees afterwards.

### Axis-specific shorthands

To check only one aspect of each run, use a dedicated shorthand.  All three
sweep modes (cross-project, between-commits, across-commits) are available
for each axis:

```python
# Fingerprint regressions only
run_fingerprint_comparison_tests(...)
run_fingerprint_comparison_tests_between_commits(...)
run_fingerprint_comparison_tests_across_commits(...)

# Scalar statistics regressions only
run_statistical_comparison_tests(...)
run_statistical_comparison_tests_between_commits(...)
run_statistical_comparison_tests_across_commits(...)

# Stdout-trajectory regressions only
run_stdout_comparison_tests(...)
run_stdout_comparison_tests_between_commits(...)
run_stdout_comparison_tests_across_commits(...)
```

These are thin wrappers around `run_simulation_comparison_tests*` that
disable the other two axes.

### Drilling into a failed test

A `FAIL` result keeps the original `CompareSimulationsTaskResult` available
as `compare_result`, so you can investigate exactly as you would with the
`compare_*` API — divergence positions, cause chains, statistic-level diff
tables are all there:

```python
for failed in r.get_fail_results():
    cr = failed.compare_result
    print(cr.fingerprint_trajectory_divergence_position.get_description())
    cr.print_divergence_position_cause_chain()
    cr.print_different_statistical_results(include_relative_errors=True)
```

See [comparing_simulations.md](comparing_simulations.md) for the full set
of investigation tools on `compare_result`.

### Aggregate result

`run_*_comparison_tests*` returns a
`MultipleCompareSimulationsTestTaskResults`, the usual test aggregate:

```python
r.num_pass        # how many configs/pairs passed
r.num_fail        # how many regressed
r.num_error       # how many failed to run
r.get_fail_results()   # iterate just the failures
r.is_all_results_pass()
```

Printing the aggregate shows the customary one-line summary used by the
rest of the test infrastructure.
