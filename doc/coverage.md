# Coverage Reports

Coverage reports show which lines, functions and branches of a project's C++
code the simulations and tests execute. They use the `coverage` build mode and
LLVM's source-based coverage tools.

## Prerequisites

- **Clang** — the project and OMNeT++ must be compiled with Clang. The
  `coverage` mode compiles with `-fprofile-instr-generate -fcoverage-mapping`
  in addition to the debug flags. See [Building](building.md) for the build
  modes.
- **`llvm-profdata` and `llvm-cov` of the same LLVM version as the compiler.**
  The raw profile format changes between LLVM versions. opp_repl takes the
  tools in this order:
  1. the environment variables `LLVM_PROFDATA` and `LLVM_COV`, if they are set;
  2. `llvm-profdata-<N>` and `llvm-cov-<N>`, where `<N>` is the major version
     of the compiler (`CXX` of OMNeT++'s `Makefile.inc`), if they are on the
     `PATH`;
  3. `llvm-profdata` and `llvm-cov`.

  On Debian and Ubuntu, the tools are in the `llvm` package or a versioned
  package, for example `llvm-18`.
- **`genhtml`** (the `lcov` package) — only for the HTML output of
  `opp_coverage_report --html`.

No extra Python packages are necessary.

## How it works

1. **Collection.** Build the project in `coverage` mode and run any tests or
   simulations with `mode="coverage"` (`-m coverage` on the command line).
   Each process that opp_repl starts in this mode gets
   `LLVM_PROFILE_FILE=<project root>/coverage/profiles/%4m.profraw`, unless
   you set the variable yourself. `%4m` names the files after the instrumented
   binary. When a process ends, the LLVM runtime merges its profile into a pool
   of at most 4 files for each binary. The disk use therefore does not grow
   with the number of runs. If you set `LLVM_PROFILE_FILE`, give an absolute
   path: opp_repl reads the pool from the folder of that path.
2. **Export.** `export_coverage()` (`opp_export_coverage`) merges the pool
   with `llvm-profdata merge -sparse` and writes an lcov file with
   `llvm-cov export`. The objects are the project's dynamic libraries in
   `coverage` mode (for example `src/libINET_coverage.so`), or its executable
   if the project builds no library. The report covers only the project's C++
   folders (`cpp_folders`). The source paths are relative to the project root.
   An optional test name marks each record with the suite that produced it.
3. **Report.** `coverage_report()` (`opp_coverage_report`) merges one or more
   lcov files, for example the exports of several test suites or CI jobs, and
   writes a summary, a history line, Markdown and, if you ask for it, HTML.

`generate_coverage_report()` and `open_coverage_report()` do all three steps
for a set of simulations and write the HTML of `llvm-cov show`. They clear the
pool before and after their runs.

## Project parameters

The `report` aspect of the `coverage` entry of the project's `test_parameters`
in its `.opp` file controls the reports:

- **`exclude`** — a list of regular expressions. `llvm-cov` leaves out each
  source file whose path matches one of them.
- **`areas`** — a folder pattern, for example `src/inet/*`. The summary gives
  the totals of each folder that matches it. Files outside these folders go
  to the area `other`.

INET's entry leaves out the generated message files and the third-party code
(the lwIP stack and `src/3rdparty`):

```python
"coverage": {"report": {"exclude": ["_m\\.(cc|h)$", "/lwip/", "/3rdparty/"], "areas": "src/inet/*"}},
```

## Python API

### A report of some simulations

```python
# run the simulations in coverage mode, then open the HTML report in the browser
open_coverage_report(simulation_project=inet_project,
                     working_directory_filter="examples/ethernet",
                     sim_time_limit="10s")

# the same without the browser; the report is in <project root>/coverage/index.html
generate_coverage_report(simulation_project=inet_project,
                         working_directory_filter="examples/ethernet",
                         sim_time_limit="10s")
```

Both functions accept the filter parameters of `run_simulations()`, and
`output_dir` (default `"coverage"`, relative to the project root).

### The coverage of test suites

```python
clear_coverage_profiles(inet_project)
run_unit_tests(simulation_project=inet_project, mode="coverage")
export_coverage(simulation_project=inet_project, output_file="unit.lcov", test_name="unit")

clear_coverage_profiles(inet_project)
run_module_tests(simulation_project=inet_project, mode="coverage")
export_coverage(simulation_project=inet_project, output_file="module.lcov", test_name="module")

summary = coverage_report(["unit.lcov", "module.lcov"], output_folder="report",
                          simulation_project=inet_project)
```

Clear the pool between two suites if you want a separate lcov file for each
suite. Clear it also after a rebuild: a profile of an older binary does not
match the new one.

### Parameters

- **`export_coverage(simulation_project, output_file, test_name)`** —
  `output_file` is the path of the lcov file (default `coverage.lcov`).
  `test_name` is written as the lcov test name (`TN`) of each record.
- **`coverage_report(lcov_files, output_folder, previous_file, html,
  simulation_project, commit, date)`** — writes these files into
  `output_folder`:
  - `coverage.lcov`, the merged counts;
  - `summary.json`, with the line, function and branch totals, and the totals
    of each area, each suite and each file;
  - `history.json`, the summary without the files on one line, to append to a
    history file;
  - `summary.md`, the totals as Markdown tables;
  - `html/`, the HTML of `genhtml`, if `html` is true.

  `previous_file` is an earlier `summary.json` or history file. The summary
  then gives the change of each total, in percentage points, against its last
  entry. `simulation_project` gives the `areas` pattern and the root folder in
  which `genhtml` finds the sources. `commit` and `date` go into the summary.

## Command line

```bash
# collect: run the tests in coverage mode
opp_run_unit_tests -p inet -m coverage
# export the pool as lcov, with the suite name
opp_export_coverage -p inet -t unit -o unit.lcov
# merge lcov files and write the report, with the change against an earlier history file
opp_coverage_report -p inet unit.lcov module.lcov -o report --previous history.jsonl --html
```

`opp_coverage_report` prints `summary.md`. It also works without a project;
then the summary has no areas.

## Coverage in CI

A CI run can collect coverage in several jobs, for example one job for each
slice of a long test suite:

1. Each job builds OMNeT++ and the project with `MODE=coverage`, runs its tests
   with `-m coverage`, and uploads the result of
   `opp_export_coverage -t <suite>`. The lcov file is small; the instrumented
   library stays in the job.
2. One report job downloads all lcov files and runs `opp_coverage_report`
   with `--previous` set to the history of earlier runs. It then appends
   `history.json` to that history.

INET's `coverage-tests.yml` workflow follows this pattern.

## Limits

- Coverage shows that code ran. It does not show that a test checked the
  result of that code.
- A process that crashes or that a signal stops writes no profile. A process
  that stops on its CPU time limit ends normally and writes its profile, but
  the lines that it reached depend on the speed of the computer.
- Only the subprocess runner sets the pool. The in-process runner and the
  opp_env runner do not.
