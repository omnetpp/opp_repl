# Coverage Reports

Coverage reports show which lines of C++ source code are exercised by
simulations.  Uses the `coverage` build mode and LLVM's coverage tools.

## Prerequisites

Coverage reports require:

- **Clang / LLVM toolchain** — the project must be compiled with Clang so that
  LLVM source-based coverage instrumentation is available.
- **`llvm-profdata`** — used to merge the raw `.profraw` profile files
  produced during simulation into a single `.profdata` file.
- **`llvm-cov`** — used to generate the HTML coverage report from the merged
  profile data.
- **OMNeT++ `coverage` build mode** — the project must be buildable in
  `coverage` mode, which compiles with `-fprofile-instr-generate
  -fcoverage-mapping`.

On Debian/Ubuntu, install the LLVM tools with
`sudo apt install llvm` (or the versioned package matching your Clang, e.g.
`llvm-17`).

No extra Python packages are required.

## How it works

Both `generate_coverage_report()` and `open_coverage_report()` follow the same
pipeline:

1. The environment variable `LLVM_PROFILE_FILE` is set to
   `coverage-%p.profraw` so that each simulation process writes its own raw
   profile file (the `%p` is replaced by the process ID).
2. The simulation project is built in `coverage` mode and the matching
   simulations are run.
3. All `coverage-*.profraw` files under the project root are collected and
   merged with `llvm-profdata merge` into a single `merged.profdata` file.
4. `llvm-cov show` is invoked with the project's coverage-mode executable and
   the merged profile data.  It produces an HTML report in the `coverage/`
   directory (or a custom directory via `output_dir`).
5. Temporary `.profraw` files and the merged profile are cleaned up
   automatically.
6. `open_coverage_report()` additionally opens `coverage/index.html` in the
   system's default browser.

The functions accept all the same filter parameters as `run_simulations()`
(e.g. `working_directory_filter`, `config_filter`, `run_number`,
`sim_time_limit`).

## Python API

### Generating and viewing a coverage report

```python
# Generate and open a coverage report in the browser
open_coverage_report(simulation_project=inet_project,
                     working_directory_filter="examples/ethernet",
                     sim_time_limit="10s")
```

### Generating a report without opening it

```python
generate_coverage_report(simulation_project=inet_project,
                         working_directory_filter="examples/ethernet",
                         sim_time_limit="10s")

# The report is written to <project_root>/coverage/index.html
```

### Covering multiple simulation directories

Run more simulations to widen coverage — all `.profraw` files under the
project root are merged into a single report:

```python
generate_coverage_report(simulation_project=inet_project,
                         working_directory_filter="examples",
                         sim_time_limit="10s")
```

### Parameters

Both functions accept:

- **`simulation_project`** — the simulation project (defaults to the current
  default project)
- **`output_dir`** — directory name for the HTML report relative to the
  project root (default `"coverage"`)
- All filter parameters from `run_simulations()`: `working_directory_filter`,
  `config_filter`, `run_number`, `sim_time_limit`, etc.

## Command Line

There are no dedicated command-line wrappers for coverage reports.  Use the
Python API from within `opp_repl`.
