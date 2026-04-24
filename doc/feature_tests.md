# Feature, Release, and All Tests

## Feature Tests

Feature tests check that simulation projects build and their simulations can be
set up correctly with different combinations of optional features enabled or
disabled.

### Prerequisites

Feature tests require:

- **`opp_featuretool`** — the OMNeT++ feature management command-line tool.
  It is included in every standard OMNeT++ installation.
- **`.oppfeatures` file** — the simulation project must declare its optional
  features in this XML file at the project root.

No extra Python packages are required.

### How it works

The project's `.oppfeatures` file declares optional features and their
associated NED packages.  For each feature the test framework creates two
test tasks:

- **Enable** — disables all features, then enables only the feature under test,
  rebuilds, and runs the simulations whose working directories match the
  feature's NED packages.
- **Disable** — enables all features, then disables only the feature under
  test, rebuilds, and runs the empty example simulation to verify the build
  still succeeds.

When no feature filter is applied, three additional whole-project tests are
added:

- **default** — resets features to their default state, rebuilds, and runs.
- **enable all** — enables every feature, rebuilds, and runs.
- **disable all** — disables every feature, rebuilds, and runs.

Tests run **sequentially** because each test modifies the feature state and
rebuilds the project.

### Python API

```python
r = run_feature_tests(simulation_project=inet_project)

# Test only a specific feature
run_feature_tests(simulation_project=inet_project, filter="VoIPStream")
```

### Understanding the test result

`run_feature_tests()` returns a `MultipleTestTaskResults` object.  Each
element in `r.results` is a `TestTaskResult` with:

- **`result`** — `"PASS"`, `"FAIL"`, or `"ERROR"`

A test **passes** when the build succeeds and all associated simulations
complete without error.  It **fails** if any simulation fails, and reports
`ERROR` on build errors.

```python
r0 = r.results[0]
print(r0.result)       # "PASS" or "FAIL"
print(r0.task.type)    # "enable", "disable", "default", "enable all", or "disable all"
print(r0.task.feature) # e.g. "VoIPStream" or None for whole-project tests
```

Re-running and filtering:

```python
r.get_fail_results().rerun()
```

> **Note:** Feature tests have no store or update step — they verify that the
> build and setup succeed, not that the results are numerically correct.
> After all feature tests complete, all features are re-enabled.

### Command Line

```bash
opp_run_feature_tests --load "/home/user/workspace/inet/inet.opp" -p inet
```

## Release Tests

Release tests run a comprehensive set of checks suitable for validating a
release build.

### Prerequisites

Release tests require OMNeT++ to be built in **all three modes** — release,
debug, and sanitize.  The binaries `opp_run_release`, `opp_run_dbg`, and
`opp_run_sanitize` must all exist; the function raises an exception otherwise.
This also implies all prerequisites of the individual test types (sanitizer
compiler support, `chart` Python packages if chart tests are desired, etc.).

### How it works

`run_release_tests()` performs the following steps:

1. Enables all features (except `SelfDoc`) and regenerates makefiles.
2. Optionally cleans and rebuilds the project in **release**, **debug**, and
   **sanitize** modes.
3. Runs `run_all_tests()`, which executes every configured test type
   (fingerprint, speed, chart, sanitizer, smoke, statistical, and feature
   tests) sequentially.

All three build modes must be available — the function raises an exception if
any of `opp_run_release`, `opp_run_dbg`, or `opp_run_sanitize` is missing.

### Python API

```python
run_release_tests(simulation_project=inet_project)

# Skip the clean and build steps (use existing binaries)
run_release_tests(simulation_project=inet_project, clean=False, build=False)
```

### Command Line

```bash
opp_run_release_tests --load "/home/user/workspace/inet/inet.opp" -p inet
```

## Running All Tests

All configured test types can be run sequentially with a single call.
`run_all_tests()` collects tasks from every available test type:

- Chart tests (if matplotlib is installed)
- Feature tests
- Fingerprint tests
- Sanitizer tests
- Smoke tests
- Speed tests
- Statistical tests

Test types that produce no matching tasks (e.g. because there are no stored
baselines) are silently skipped.

### Python API

```python
r = run_all_tests(simulation_project=inet_project)
```

The result is a `MultipleTestTaskResults` where each element corresponds to
the results of one test type.

### Command Line

```bash
opp_run_all_tests --load "/home/user/workspace/inet/inet.opp" -p inet
```
