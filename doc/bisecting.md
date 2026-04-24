# Bisecting Git Commits for Test Failures

When a test starts failing, you often need to find the exact commit that
introduced the regression.  The bisect functions perform an automatic
binary search over a range of git commits — similar to `git bisect`, but
fully integrated with the test infrastructure so that each candidate
commit is built, tested, and evaluated automatically.

## How it works

1. You provide a **good** commit (where the test passes) and a **bad**
   commit (where it fails).
2. The bisect function enumerates all commits between the two using
   `git rev-list --ancestry-path`.
3. It verifies that the good commit really passes and the bad commit
   really fails.
4. It performs a binary search: at each step, a middle commit is checked
   out as a **temporary git worktree**, built, and tested.
5. Depending on whether the result is good or bad, the search range is
   narrowed.
6. When the search converges, the **offending commit** — the first one
   that causes the failure — is reported.

Each worktree is created next to the original repository root so that the
original working tree is never modified.  Baseline results (fingerprints,
statistics, speed measurements, etc.) are automatically loaded from the
good commit.

## Supported test types

There is a convenience wrapper for each test type:

| Function | Test type |
|----------|-----------|
| `bisect_fingerprint_tests()` | Fingerprint tests |
| `bisect_statistical_tests()` | Statistical tests |
| `bisect_smoke_tests()` | Smoke tests |
| `bisect_speed_tests()` | Speed tests |
| `bisect_chart_tests()` | Chart tests |
| `bisect_sanitizer_tests()` | Sanitizer tests |

All wrappers accept the same `simulation_project`, `good_hash`, and
`bad_hash` arguments, plus any keyword arguments supported by the
underlying test runner (e.g. `working_directory_filter`, `config_filter`,
`sim_time_limit`).

## Python API

### Basic usage

```python
result = bisect_fingerprint_tests(
    simulation_project=inet_project,
    good_hash="v4.5.0",
    bad_hash="master",
    sim_time_limit="1s",
)
```

This finds the first commit between `v4.5.0` and `master` that causes a
fingerprint test to fail.  Tags, branch names, and full/short commit
hashes are all accepted.

### Narrowing the scope

You can pass any filter supported by the underlying test runner to limit
which simulations are tested at each step.  This makes bisecting much
faster when you already know which area is affected:

```python
result = bisect_fingerprint_tests(
    simulation_project=inet_project,
    good_hash="abc1234",
    bad_hash="def5678",
    working_directory_filter="examples/ethernet",
    config_filter="MixedLAN",
    sim_time_limit="10s",
)
```

### Other test types

```python
# Statistical tests
result = bisect_statistical_tests(
    simulation_project=inet_project,
    good_hash="v4.5.0",
    bad_hash="master",
)

# Smoke tests
result = bisect_smoke_tests(
    simulation_project=inet_project,
    good_hash="v4.5.0",
    bad_hash="master",
)

# Speed tests
result = bisect_speed_tests(
    simulation_project=inet_project,
    good_hash="v4.5.0",
    bad_hash="master",
)
```

### Understanding the result

Every bisect function returns a `BisectResult` object:

```python
print(result)
# Bisect result: offending commit abc1234567 found in 7 steps across 128 commits (v4.5.0..master) in 0:12:34
```

Attributes of `BisectResult`:

- **`offending_commit`** — full git hash of the first bad commit
- **`result`** — the test result object from the offending commit
- **`num_steps`** — number of bisect steps performed
- **`num_commits`** — total commits in the search range
- **`good_hash`** / **`bad_hash`** — the original bounds passed by the caller
- **`steps`** — list of `(commit_hash, result, is_good)` tuples for every tested commit
- **`elapsed_wall_time`** — total wall-clock time of the bisection
- **`error_message`** — set when bisection could not complete (e.g. the good commit does not actually pass)

### Inspecting individual steps

```python
for commit, step_result, is_good in result.steps:
    verdict = "GOOD" if is_good else "BAD"
    print(f"{commit[:10]} {verdict}")
```

### Using the low-level API

The convenience wrappers call `bisect_simulations_between_commits()` with
the appropriate test runner.  You can call it directly for custom test
logic:

```python
result = bisect_simulations_between_commits(
    simulation_project=inet_project,
    good_hash="v4.5.0",
    bad_hash="master",
    run_function=run_fingerprint_tests,
    is_good_result=lambda r: r.is_all_results_expected(),
    sim_time_limit="1s",
)
```

Parameters:

- **`simulation_project`** — the project whose git repository is bisected
- **`good_hash`** / **`bad_hash`** — bounds of the commit range
- **`run_function`** — called as `run_function(simulation_project=..., **kwargs)` for each candidate commit
- **`good_result`** — expected `result` attribute value for good commits (default `"PASS"`); ignored when `is_good_result` is provided
- **`is_good_result`** — optional predicate `is_good_result(result) -> bool` for custom pass/fail logic
- **`update_good_results_function`** — optional; when provided, called on the good commit to refresh baseline data before testing begins
- **`build_log_level`** / **`simulation_log_level`** — control verbosity during bisection (default `"WARN"`)

## Example: finding a fingerprint regression in INET

Suppose fingerprint tests pass on the `v4.5.0` tag but fail on the
current `master` branch.  Here is a complete REPL session that locates
the offending commit:

```python
# Load the workspace
In [1]: load_opp_file("inet.opp")

# Confirm the failure exists
In [2]: r = run_fingerprint_tests(simulation_project=inet_project, sim_time_limit="1s")
# Multiple fingerprint test results: FAIL, summary: 3 FAIL, 39 PASS in 0:00:01.567479

# Bisect to find the culprit
In [3]: b = bisect_fingerprint_tests(
   ...:     simulation_project=inet_project,
   ...:     good_hash="v4.5.0",
   ...:     bad_hash="master",
   ...:     sim_time_limit="1s",
   ...: )
# Verifying good v4.5.0     GOOD ...
# Verifying bad  master      BAD  ...
# Step  1/128   a1b2c3d4e5  GOOD ...
# Step  2/128   f6a7b8c9d0  BAD  ...
# ...
# Bisect complete: offending commit is e1f2a3b4c5 (found in 9 steps)

# Inspect the result
In [4]: print(b)
# Bisect result: offending commit e1f2a3b4c5 found in 9 steps across 128 commits (v4.5.0..master) in 0:08:42

# View the offending commit
In [5]: !git -C /home/user/workspace/inet log --oneline -1 e1f2a3b4c5
# e1f2a3b4c5 Refactored MAC address resolution

# Narrow a re-bisect to only the failing area for faster results
In [6]: b2 = bisect_fingerprint_tests(
   ...:     simulation_project=inet_project,
   ...:     good_hash="v4.5.0",
   ...:     bad_hash="master",
   ...:     working_directory_filter="examples/ethernet",
   ...:     sim_time_limit="1s",
   ...: )
```

## Tips

- **Narrow your filters** — the fewer simulations tested at each step, the faster the bisect completes.  Use `working_directory_filter`, `config_filter`, and `sim_time_limit` to focus on the failing area.
- **Use short sim_time_limit** — if the failure reproduces with a short time limit, set it explicitly to speed up each step.
- **Check the steps** — if the result seems wrong, inspect `result.steps` to see whether any commits had unexpected outcomes (e.g. non-monotonic failures).
- **Tags and branches work** — `good_hash` and `bad_hash` accept anything that `git rev-list` understands: tags, branch names, and commit hashes.
