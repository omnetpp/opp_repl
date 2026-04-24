# Sanitizer Tests

Sanitizer tests detect memory errors, undefined behavior, and other
bugs by running simulations with AddressSanitizer / UBSan instrumentation.
Uses the `sanitize` build mode.

## Prerequisites

Sanitizer tests require:

- **A compiler with sanitizer support** — GCC or Clang with support for
  `-fsanitize=address,undefined`.  Most modern Linux and macOS toolchains
  include this.
- **OMNeT++ `sanitize` build mode** — OMNeT++ must be configured so that the
  `sanitize` mode is available (i.e. `opp_run_sanitize` exists).  The project
  is built in this mode automatically before the tests run.

No extra Python packages are required.

## How it works

The project is built in `sanitize` mode, which enables compiler
instrumentation (AddressSanitizer, UndefinedBehaviorSanitizer).  Each
simulation is then run normally.  After the simulation finishes, the
test checks `stderr` for a `SUMMARY:` line emitted by the sanitizer
runtime.  If such a line is found the test fails with the sanitizer
summary as the reason.

By default, simulations are limited by a CPU time limit (`cpu_time_limit`,
default `"1s"`) instead of simulation time to keep sanitizer runs
practical, since instrumented builds are significantly slower.

## Python API

### Running sanitizer tests

```python
r = run_sanitizer_tests(simulation_project=inet_project)

# Filter to a specific area with a longer time limit
run_sanitizer_tests(simulation_project=inet_project,
                    working_directory_filter="examples/ethernet",
                    cpu_time_limit="10s")
```

### Understanding the test result

`run_sanitizer_tests()` returns a `MultipleTestTaskResults` object.  Each
element in `r.results` is a `SimulationTestTaskResult` with:

- **`result`** — `"PASS"`, `"FAIL"`, `"SKIP"`, `"ERROR"`, or `"CANCEL"`
- **`reason`** — on `FAIL`, the sanitizer summary line (e.g. `"AddressSanitizer: heap-buffer-overflow ..."`); on `PASS`, `None`

```python
r0 = r.results[0]
print(r0.result)   # "PASS" or "FAIL"
print(r0.reason)   # e.g. "AddressSanitizer: heap-buffer-overflow ..."
```

A simulation that completes without any sanitizer output is reported as
`PASS`.  A simulation that crashes or exits with an error before the
sanitizer reports anything is reported as `ERROR`.

### Re-running and filtering

```python
# Re-run only the failures
r.get_fail_results().rerun()

# Filter to a specific config
run_sanitizer_tests(simulation_project=inet_project,
                    config_filter="General",
                    working_directory_filter="examples/ethernet")
```

### Parameters

`get_sanitizer_test_tasks()` accepts the same filter parameters as
`get_simulation_tasks()`, plus:

- **`mode`** — build mode (default `"sanitize"`)
- **`cpu_time_limit`** — CPU time limit per run (default `"1s"`)
- **`run_number`** — run number to test (default `0`)

> **Note:** Sanitizer tests have no store or update step — there is no
> baseline to maintain.  A test passes when the sanitizer reports no issues.

## Command Line

```bash
opp_run_sanitizer_tests --load "/home/user/workspace/inet/inet.opp" -p inet
```
