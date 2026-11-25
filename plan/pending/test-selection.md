# Change-based test selection

> **Status:** phase 0 started · **Owner:** opp_repl · **Also changes:** INET (weekly coverage
> workflow, `inet.opp`), the `inet-framework/coverage` repository, optionally omnetpp (section 11)

For a change, find the tests whose outcome can differ, in every test suite, and run only those
tests. A full run of all suites with the coverage build of opp_repl (`-m coverage`) makes a **test
map**: for each test, the functions, NED types, ini sections and files that the test used. The
selection reads the map and the diff, and it selects each test that the map cannot prove to be
unaffected.

The map run is the weekly coverage run that exists now, with one change: each run writes its own
profile. The same profiles give the present coverage report and the map. The map goes into the
`inet-framework/coverage` repository next to the report, so that people can browse it.

## 1. The problem

A developer changes some lines and then runs thousands of tests. INET has 5784 fingerprint
entries, 1195 protocol tests, 845 module tests, 153 unit tests and 77 queueing tests. The
statistical, chart, smoke, sanitizer, speed, validation and feature tests come on top. A change in
`Ipv4.cc` cannot change most of these tests, but nothing tells which ones.

**Goal.** For a change (a commit, a commit range, the working tree, or a patch file), give for each
suite the set of tests that can have a different outcome. A test that the selection skips has the
outcome that it had at the base commit.

**Correct means conservative.** The selection can select too many tests. It must never skip a test
whose outcome changes. If the map does not know something, the test is selected.

**Not a goal:** test priority, flaky-test detection, or the removal of the full runs. The weekly full
run stays, and it makes the map.

## 2. What exists now

- `opp_repl/simulation/dependency.py` has `SimulationTaskDependencyStore`. It works at the level of
  `.oppfeatures` features. A simulation run with `--print-instantiated-ned-types=true` gives the NED
  types that the run instantiated. The store maps them to packages and then to features. A changed
  file selects the configs that use its feature, and a file outside all feature folders selects all
  configs.
- `get_simulation_tasks(affected_by_modification_filter=...)` in `opp_repl/simulation/task.py:853`
  applies the store. It takes a list of files, a commit or a range, and it reads only file names
  from git, not the hunks.
- No CLI option, no CI workflow and no opp_ci code uses the filter. `inet.opp` does not set
  `dependency_store`, so opp_repl looks for `dependency.json` in the INET root. The INET file is
  `tests/dependency.json`, so the default lookup does not find it.
- The filter applies only to simulation configs. The opp tests (unit, module, packet, queueing,
  protocol), the chart tests and the feature tests have no selection.
- omnetpp 6.1 has `print-instantiated-ned-types` (`src/sim/csimulation.cc`, `cUsageCollector`). It
  prints only the concrete type of each component. It does not print base types (`extends`),
  interfaces (`like`), or types that a lookup found but did not instantiate.
- omnetpp has `-q sectioninheritance`, which prints the section chain of a config.
- opp_repl has a `coverage` build mode: LLVM source-based coverage
  (`-fprofile-instr-generate -fcoverage-mapping`) on top of the debug flags (`-O0`, no `NDEBUG`).
  `project.py:673` sets `LLVM_PROFILE_FILE=<pool>/%4m.profraw`, so the LLVM runtime merges all
  processes into 4 files for each binary.
- The weekly INET coverage workflow (`coverage-tests.yml`, Sunday 16:00 UTC, master only) runs the
  fingerprint tests in 4 splits and the unit, module, packet, queueing and protocol suites in
  coverage mode, and the inet-gpl packetdrill suite. It writes one lcov file for each suite. The
  merge removes the information about which test ran which code. The workflow does not run the
  statistical, smoke, sanitizer, speed, chart, validation and feature tests.
- The report job publishes to `inet-framework/coverage`: the `master` branch holds `README.md`,
  `history.jsonl` and `latest.json`; the `gh-pages` branch holds the `genhtml` HTML, and each week
  replaces it with a new orphan commit. The address is `https://inet.omnetpp.org/coverage/`. The
  repository is 11 MB now.
- The report job of the weekly runs of 2026-11-15 and 2026-11-22 failed. `genhtml` stops on the
  merged lcov file: `src/inet/networklayer/contract/L3Socket.cc:48: line is not hit but at least
  one branch on line has been evaluated` (error class `inconsistent`). The last published report is
  from 2026-11-08 (INET 7ec0d4d3f3).
- `opp_repl/test/coverage.py` already has the parts that the map needs: `get_coverage_objects`
  (the coverage binaries), `get_coverage_tool` (the `llvm-profdata` and `llvm-cov` of the compiler
  version), `merge_coverage_profiles` and `export_coverage`.
- The 5784 fingerprint entries are 1847 distinct runs (config, run number, sim time limit). Each
  run has 3 ingredient sets.
- omnetpp has no event-count limit. The limit options are `sim-time-limit`, `cpu-time-limit` and
  `real-time-limit`.
- INET: 1770 `.cc` files, 2042 `.h` files, 1719 NED files and 346 ini files. 15 C++ files have
  `NDEBUG` conditionals.

## 3. Words in this plan

| Word | Meaning |
| --- | --- |
| test | One item of one suite, with a stable key, for example `fingerprint:examples/adhoc/hostautoconf/omnetpp.ini:General:#0:100s:tplx` |
| run | One process that a test starts: a simulation, an opp test binary, a build. A test has one or more runs. |
| input | Anything whose content can change the outcome of a test |
| test map | The files that hold, for each test, the inputs that its runs used at the map commit |
| map run | The weekly full run of all suites with `-m coverage` that makes the test map and the coverage report |
| A, B, C | A is the map commit. The change goes from the base B to the target C. C can be the working tree. |
| hunk | One part of a diff, with the old line range (at A) and the new line range |

## 4. The correctness rule

### 4.1 Why a skip is correct

A deterministic test reads its inputs and computes its outcome from them. If no input that the test
read at A has different content at C, then the test reads the same values at C, takes the same path
and gives the same outcome. So the map must hold a **superset** of what each test read. More
entries make the selection wider but still correct. A missing entry makes the selection wrong.

### 4.2 An old map

The map tells what the tests read at A, not at B. A change in A..B can make a test read a file
that it did not read at A. So the selection does not use diff(B,C). It uses
**diff(A,B) ∪ diff(A,C)**:

- If diff(A,B) does not touch the inputs of test T, then outcome(B) = outcome(A).
- If diff(A,C) does not touch the inputs of T, then outcome(C) = outcome(A).
- If both are true, outcome(B) = outcome(C), and the selection can skip T.

When A = B, this is diff(B,C). A new map makes the selection narrow. An old map makes it wide, and
the selection report shows how much the age of the map costs. The hunks of diff(A,·) have old line
numbers at A, which is what the function table of the map needs.

### 4.3 Tests that are always selected

- A test that is not in the map: a new test, a new config, a new run number.
- A test whose map entry did not end normally (error, crash, time limit). Its inputs can include
  name lookups that failed, and the map does not record those.
- A test that is not deterministic: real-time scheduler, emulation, `ExternalProcess`, threads
  (the `OpenMP` feature), and a list in the `test_selection` aspect of `test_parameters`.
- All tests, if the environment differs from the map: the omnetpp commit, the opp_repl commit, the
  compiler version, the feature state, or the versions of the external libraries.

### 4.4 Assumptions

The fingerprint tests already make these assumptions. The plan writes them down:

1. The outcome does not depend on the addresses of code or data. ASLR already changes them from run
   to run.
2. The code has no undefined behavior that makes `-O0` and `-O3` take different paths. The
   sanitizer tests examine this.
3. There are no ODR violations: each inline or template function has the same definition in all
   translation units.
4. Code that only a release build compiles (`#ifdef NDEBUG`) is handled by rule R-NDEBUG (5.1).

## 5. Inputs and rules

Each input class has a record (what the map run stores) and rules (which tests a changed file
selects). A file belongs to the first class whose rule applies.

### 5.1 C++ code (`.cc`, `.h`, the generated `_m.cc` and `_m.h`)

**Record.**

- For each run, the functions that ran: the functions with an entry count above zero in the LLVM
  profile of that run. The static initialization functions (`__cxx_global_var_init*`,
  `_GLOBAL__sub_I_*`) run in each process, so the record leaves them out, and rule R6 covers them.
- Once for each map, a function table from the coverage mapping (`llvm-cov export`): the mangled
  name, the source file and the line range of the body.
- For each function, the translation units that emit it, from `nm --defined-only` of the object
  files. The linker keeps one copy of an inline or template function, so the binary does not tell
  this.
- For each translation unit, the headers that it includes, from the `.d` files of the build. The
  test binaries of the opp tests are translation units too.

**Rules for one hunk.** Here "tests of TU X" means the tests that ran a function that X emits.

| Rule | Hunk | Selected tests |
| --- | --- | --- |
| R1 | Only comments or white space, and no line shift | none |
| R2 | Inside the body of function f, at A | the tests that ran f (all instantiations) |
| R3 | Comment or white space only, with a line shift | as R2, for each function below the hunk in the file, because `__LINE__` changes (`ASSERT`, error messages) |
| R4 | In a `.h` file, outside all function bodies: class definition, declaration, macro, constant, default member value, `#include` | the tests of each TU that includes the header, at A or at C |
| R5 | Inside a `constexpr` or `consteval` function | as R4, because the compiler can evaluate it, and then no counter shows it |
| R6 | In a `.cc` file, outside all function bodies: global data, static members, registration macros (`Define_Module`, `Register_Class`, `Register_Serializer`, and other items), `#include`, `using` | all tests that load the library, because the static initialization of each process runs this code |
| R7 | A new or a removed `.cc` file | all tests that load the library (static initialization) |
| R8 | A new `.h` file | none, because only a changed file can include it, and that file has its own hunk |
| R9 | A removed `.h` file | as R4 |
| R10 | A `.msg` file | v1: the tests of the TUs that include the generated `_m.h`, and the tests that ran a function of the `_m.cc`. v2: generate the `_m` files at both sides and apply R1–R9 to their diff. |
| R11 | Build files: `Makefile`, `makefrag`, `.oppbuildspec`, `.oppfeatures`, `.oppfeaturestate`, the build fields of `inet.opp` | all tests |
| R-NDEBUG | A function g has a release-only block (`#ifdef NDEBUG`, or the `#else` of `#ifndef NDEBUG`) that calls project functions | the map adds these callees to each run in release mode that ran g. A scan of the 15 files makes the list. |

A hunk that is not fully inside a known function body is "outside all function bodies". This
includes the signature line and the member initializer list of a constructor. This default is
conservative: an unknown place gets the wider rule.

R6 and R7 are wide. A new module class (new `.cc` with `Define_Module`) selects all tests. The
replay (section 10) shows how often this occurs. A later refinement can treat registrations that
other code finds only by name as narrow.

### 5.2 NED

**Record.** For each run, the instantiated NED types (`print-instantiated-ned-types`). The selection
adds to them, from the NED sources at A: the base types (`extends`, the full chain), the interfaces
that these types implement, the interfaces of `like` submodules and channels, and the file that
declares each type. Option O1 (section 11) moves this to omnetpp.

**Rules.**

| Rule | Change | Selected tests |
| --- | --- | --- |
| N1 | Changed NED file, the same declared types | the tests that used a type of this file |
| N2 | Types added, removed or renamed, a changed package, a new or removed NED file | N1, and the tests that used a type with the same simple name as an added type, because a name lookup can find another type |
| N3 | `package.ned` (package, `@namespace`) | the tests that used a type in the package or below it |
| N4 | The NED path at C does not load (syntax error, duplicate type) | all simulation tests, because each simulation loads all NED files |
| N5 | NED file outside the NED path | rule F1 (data file) |

### 5.3 ini

**Record.** For each run: the ini file, the config, the section chain (`-q sectioninheritance`), and
the included files (from the file trace, 5.4).

**Rules.**

| Rule | Change | Selected tests |
| --- | --- | --- |
| I1 | Changed ini file | parse both sides; compare each section as an ordered list of entries (the first match wins, so the order is important); select the tests whose chain contains a changed section |
| I2 | A changed file that an ini file includes | v1: all tests that read it; v2: the I1 logic at the position of the `include` line |
| I3 | Parse error, or a change of iteration variables or `repeat` | all tests of the ini file. New run numbers also make new test keys (4.3). |

### 5.4 Other files (data)

**Record.** For each run, each file and directory that the process opened, examined (`stat`,
`access`) or listed. The record includes lookups that failed. The tool is a file trace of the
process tree (`strace -f -e trace=%file`, or an `LD_PRELOAD` library; phase 0 measures both). The
trace also covers `xmldoc()`, `readCSV()`, mobility traces, pcap input, audio files and other
files that INET reads directly.

**Rules.**

| Rule | Change | Selected tests |
| --- | --- | --- |
| F1 | A changed, new or removed file | the tests whose trace contains the path, also as a lookup that failed |
| F2 | A new or removed file in a directory | the tests that listed the directory |
| F3 | A file that no test read and that no other rule claims | none |

The NED and ini rules come before F1 for their files, because they are narrower. Each simulation
reads all NED files, so F1 would select all tests for each NED change.

### 5.5 Expected results

| Rule | Change | Selected tests |
| --- | --- | --- |
| E1 | `tests/fingerprint/store.json` | the tests whose entry changed (compare by key) |
| E2 | The `statistics` baseline pin in `inet.opp` | diff the statistics repository between the two pins; select the configs of the changed result files |
| E3 | The `media` baseline pin | the same for the chart images |
| E4 | `tests/speed/store.json` | the tests whose entry changed |
| E5 | Other fields of a test kind in `test_parameters` | all tests of that kind |
| E6 | A `.test` file | that opp test. The expected output and the test code are in the file. |

### 5.6 The test harness

| Rule | Change | Selected tests |
| --- | --- | --- |
| H1 | opp_repl commit differs from the map | all tests; an option accepts the harness as unchanged |
| H2 | INET `python/` (validation runner, chart code) | all chart and validation tests (v1) |
| H3 | A `.anf` file | the chart tests of this file |
| H4 | `tests/protocol/lib` and other test libraries | the C++ rules, because the coverage build compiles them |
| H5 | omnetpp commit differs from the map | all tests (v1). Later: compile omnetpp in coverage mode and apply 5.1 to its sources |

## 6. The suites

The map records each distinct run once. Two tests that start the same run share one record.

| Suite | Test key | Runs | Map run differs from the test by |
| --- | --- | --- | --- |
| fingerprint | config, run, sim time limit, ingredients | one simulation | nothing; the ingredients change only the hash, so one record serves all ingredient sets |
| statistical | config, run 0 | one simulation, release | coverage build; R-NDEBUG covers the release-only code |
| smoke | config, run 0 | one simulation, 1 s CPU time | the bound, see section 7 |
| sanitizer | config, run 0 | as smoke, sanitizer build | as smoke; the sanitizer only examines code that ran |
| speed | config, run | one simulation | nothing; see the note below |
| chart | `.anf` file, chart | the simulations that the chart reads, and the chart code | the chart code runs in the traced process |
| validation | validation test | the simulations of the runner | the traced process tree of the runner |
| unit, module, queueing, protocol | `.test` file | opp_test generates, compiles and runs one test binary | `LLVM_PROFILE_FILE` for each test; the `.d` files of the test build go into the map (R4) |
| packet | test of `packet_test` | one binary for all tests | the map records one run for the binary; all packet tests share it |
| feature | feature | a build without the feature, then smoke runs | v1: each change of a C++, msg, NED or build file selects all feature tests; the smoke runs follow section 7 |

**Speed.** The rules select the speed tests whose code changed. A change in code that a test did not
run can still change its speed a little (code layout, cache). The speed tests are noisy, so the
plan accepts this and keeps them in the weekly full run.

The speed tests cannot run now. They give `--measure-cpu-usage=true` to each run, and omnetpp
(`omnetpp-6.x`, `master`) has no such option, so each run stops at startup with `Unknown
command-line configuration option --measure-cpu-usage`. Until omnetpp has the option, the speed
suite has no map records, and the weekly run does not include it.

**The build** is not a test that the selection skips. It runs before each selection.

## 7. CPU-time limits and the end of a run

Smoke, sanitizer and feature tests stop after 1 s of CPU time. How far a run gets depends on the
machine and on the build. If the map run gets less far than a real run, the map is too small, and
the selection is not correct.

A run to a later point is a superset only for the event loop. `finish()` runs at the stop point, and
its path can depend on the state at that point. So a run to a deterministic bound is correct only
for the same bound.

Two options:

- **D2a (recommended).** Make the bound deterministic. Add an event-count limit to omnetpp (O2),
  and change the smoke, sanitizer and feature tests from `cpu_time_limit=1s` to an event limit that
  is about 1 s on the CI machine. The `cpu_time_limit` stays as a safety stop, as in the fingerprint
  tests. Then the map run uses the same bound, and the record is exact.
- **D2b.** Keep the CPU-time limit. The map run uses K × the limit (K=10 by default) and records the
  last event number. The real test also logs its last event number. If a real run gets past the
  recorded event, opp_repl gives a warning and selects the test until the next map. This is correct
  in practice but not proven, because of `finish()`.

The fingerprint and statistical tests already have a deterministic bound (the sim time limit), so
they do not have this problem.

## 8. The test map

### 8.1 One run, two outputs

The map run and the present coverage report use the same build (`-m coverage`, the
`INET_coverage` library and executable that opp_repl already builds) and the same test runs. Only
`LLVM_PROFILE_FILE` changes:

- Now: `<pool>/%4m.profraw`. The LLVM runtime merges all processes of a suite into 4 files.
- Map run: `<pool>/<run id>/%p.profraw`. Each run writes its own files. Directly after the run,
  opp_repl merges them into a sparse `<run id>.profdata` (only the functions that ran), reads the
  function list from it, and removes the `.profraw` files.

At the end of a suite, `llvm-profdata merge` of the per-run `.profdata` files gives the suite
profile. `opp_export_coverage` writes the same lcov file from it as now, so the coverage report does
not change. Phase 1 compares the two lcov files of one suite to make sure of this.

The map needs more suites than the present run (section 6): statistical, smoke, chart, validation
and speed. Statistical, smoke, chart and validation come into the weekly run in phase 0 (user
decisions of 2026-11-25), and the coverage report then also includes them. Speed cannot run now
(section 6).
The run stays weekly and only on master (the maintainer decision D12 of the coverage plan).

### 8.2 Content

- Header: project, map commit A, omnetpp commit, opp_repl commit, compiler, feature state, the
  versions of the external libraries, date.
- Run table: a stable short id for each run (a hash of its key), the key, the end status, the last
  event number and sim time, the ini file and the section chain.
- Test table: kind, key → run ids.
- For each input file that a run used, one record (8.3).
- Include table: TU → project headers. Release-only callees (R-NDEBUG).

### 8.3 Layout for browsing

The map is a tree of text files that has the same paths as the project. Each file tells which runs
used which part of the source file of the same name:

| Map file | Content |
| --- | --- |
| `map/src/inet/networklayer/ipv4/Ipv4.cc.json` | for each function: the body line range, the name, the run ids; and the TUs that emit it |
| `map/src/inet/networklayer/ipv4/Ipv4.ned.json` | for each declared type: the run ids |
| `map/examples/.../omnetpp.ini.json` | for each section: the run ids |
| `map/<path>.json` of a data file | the run ids that opened or looked up the file |
| `map/<folder>/index.json` | for the folder: the number of runs that used something below it, for each kind |
| `map/runs.json`, `map/tests.json`, `map/header.json` | the tables of 8.2 |

A set that contains almost all runs is written as "all except ...". Phase 0 measures if this is
enough, or if the map also needs a table of shared run sets.

With this layout:

- A person can read on GitHub which tests use a file or a function. The diff of a week shows how the
  use changed.
- Git stores only the changed files of each week, so the history stays small.
- The selection reads only the map files of the changed source files.

### 8.4 Location

The map goes into the `master` branch of `inet-framework/coverage`, in the folder `map/`, next to
`history.jsonl`. Each weekly commit of the report job writes the map of its INET commit. To find
the map for base B, opp_repl looks in the history of `master` for the newest map whose INET commit
is an ancestor of B, and it reads that version with `git show`.

The `gh-pages` branch gets a small viewer page. It reads the `map/` files and shows, for a source
file or a folder, the tests that used it. Links from the `genhtml` pages of each file go to the
viewer. The `gh-pages` branch is replaced each week, so the viewer adds no history.

The history of `master` can lose old commits (user decision, 2026-11-25). The report job keeps the
commits of the last N weeks. When the history gets longer, the job makes a new root commit with the
tree of the oldest kept week, puts the newer commits on top of it, and does a force push. The file
`history.jsonl` keeps all summary lines, so the coverage history does not get shorter. Phase 0
measures the size of a weekly map and sets N. A base commit that is older than the oldest kept map
gets no map, and then the selection selects all tests.

A developer can also make a map locally (`opp_update_test_map`).

### 8.5 Reverse queries

`opp_show_test_map` answers "which tests used this file, function, NED type or ini section", "what
did this test use", and gives the summary for each folder. It reads the same files as the viewer.

## 9. The selection

**Commands.**

- `opp_select_tests -p inet --changes <rev | rev..rev | worktree | patch file> [--map <file>]
  [--kind <kind>...] [--explain]` prints the selected tests of each kind. `--explain` gives the rule
  and the changed place that selected each test. The summary gives "selected N of M" for each kind.
- `--changes` on each `opp_run_*_tests` command and on `opp_run_all_tests`. This option replaces
  `affected_by_modification_filter`.

**Steps.**

1. Find B (for a branch: the merge base with master) and A (the newest map commit that is an
   ancestor of B).
2. Get diff(A,B) and diff(A,C) as hunks, with the file content of both sides from git.
3. Give each file a class (5.1–5.6) and apply its rules to each hunk.
4. Add the tests of 4.3.
5. Print the result. An inverted index (function → runs, file → runs, NED type → runs) makes the
   lookups fast.

## 10. How we make sure that the selection is correct

- **V1 Replay of the history.** The INET history has ground truth. Each commit that changed a
  fingerprint entry of test T must select T. Each commit that moved the `statistics` or `media` pin
  must select the tests of the changed baseline files. A missed test is a defect in a rule. The
  replay also gives the selection ratio for each commit, which is the measure of usefulness.
- **V2 Shadow check in CI.** The weekly full run computes the selection for the range from the last
  map commit to the new commit. It compares the selection with the tests whose outcome changed
  between the two full runs. A changed test that the selection skipped makes the job fail.
- **V3 Mutation sample.** Change a constant in a sample of functions that ran, run all tests, and
  compare. The tests whose fingerprint changed must be a subset of the selection. This is expensive,
  so do it once for some functions.

## 11. Proposed omnetpp changes

All are optional. Each one removes a workaround in opp_repl.

| Id | Change | Without it |
| --- | --- | --- |
| O1 | The usage collector also prints the base types, the interfaces and the failed lookups of NED types, with the file of each declaration | opp_repl computes the closure from the NED sources; failed lookups stay unknown (4.3) |
| O2 | An event-count limit config option | D2b (section 7) |
| O3 | Print the included ini files of a run | the file trace gives them |

## 12. Steps

### Phase 0 — repair the weekly report, and measure

- [x] Repair the report job of the weekly coverage workflow (section 2: `genhtml` stops on
  `L3Socket.cc:48`). The map run builds on this workflow.
  - Cause: `ubuntu-latest` became Ubuntu 26.04 between the runs of 2026-11-08 and 2026-11-15. The
    tests jobs went from clang 18 to clang 21, and the report job went from `lcov` 2.0 to `lcov`
    2.4. The coverage code of opp_repl did not change (36d35ee..155ac50).
  - The data is correct LLVM output. `llvm-cov` puts the branch counts of a `switch` case on the
    `case` line. When the case never ran, the line count is 0, but the "not this case" branch has
    a count. The 9 lcov files of 2026-11-22 have 0 to 1309 such lines each. `lcov` 2.4 stops on
    them (`inconsistent`).
  - clang 21 also writes branch records for `ASSERT` lines without a line record. `lcov` 2.0 cannot
    read this data with any option. This combination does not occur in CI.
  - Repair: `genhtml --ignore-errors inconsistent,inconsistent,unsupported,unsupported`. The counts
    stay as `llvm-cov` wrote them. `lcov` 2.0 accepts the option.
  - Checked: the commands of the report job in `ubuntu:26.04` (`lcov` 2.4-3) with the 9 lcov files
    of the run of 2026-11-22 (INET 858477687b) write the summary and the HTML (160 MB): lines
    68.46%, functions 68.68%, branches 57.91%. The branch rate went up by 4.64 points, because
    clang 21 writes more branch records.
  - Checked on GitHub: the manual run 45588176059 (INET c7e7cdaabd) passed in all 6 jobs. Lines
    68.5%, functions 68.9%, branches 58.1%.
- [x] Add the statistical, chart, smoke and validation tests to the weekly coverage run (D6). INET
  commit 0798401b78 on the local branch `topic/coverage-more-suites` (worktree
  `inet-coverage-more-suites`), not pushed.
  - New jobs: `statistical-0` and `statistical-1` (945 tests in 2 splits), `chart` (236 charts,
    4752 simulations), `smoke` (945 runs) and `validation` (8 tests). Each writes one lcov file
    with the name of its suite. `-m coverage` replaces the release mode of the `inet.opp` defaults.
  - `omnetpp.scave` loads only the bindings `scave_bindings`, `scave_bindings_dbg` and
    `scave_bindings_sanitize`, not `scave_bindings_coverage`. A coverage job builds omnetpp only in
    coverage mode, so the statistical, chart and validation jobs also run
    `make MODE=release scave` in omnetpp (23 s on 32 cores in a new tree).
  - Times in release mode on GitHub: statistical 18 minutes, chart 15 minutes (simulations),
    validation 24 s. Coverage mode is about 6 times slower (fingerprint split 0: 3.9 minutes in
    release, 22.6 in debug, 24.3 in coverage). The chart test runs all its simulations before the
    split applies (`MultipleChartTestTasks.run_protected`), so the chart job is one job with a
    timeout of 240 minutes.
  - Each coverage job compiles INET from the start (32 minutes on GitHub): the restore found no
    `native-coverage-ccache` cache.
  - Checked locally (coverage build of 28f1dc534c): samples of the four commands as `run_suite`
    runs them pass, and each export gives an lcov file with its test name and hit lines.
- [ ] Run the workflow of the branch on GitHub, and record the job times.
- [ ] Build INET with `-m coverage`. Run 20 fingerprint tests, each with its own `LLVM_PROFILE_FILE`.
- [ ] Measure: size of one `.profraw`, time to reduce it to the functions that ran
  (`llvm-profdata merge -sparse` and `show --all-functions`, or `show` on the raw file), the
  number of functions in the binary, functions for each run.
- [ ] Measure the overhead of `strace -f -e trace=%file` and of an `LD_PRELOAD` trace on the same
  20 runs. Examine if `strace` works in the podman and GitHub containers.
- [ ] Measure the time of `llvm-cov export` for the function table and of `nm` over all objects.
- [ ] List the release-only blocks in the 15 `NDEBUG` files.
- [ ] Write the map of the 20 runs in the layout of 8.3 for two INET commits one week apart.
  Measure the size of each map, and the growth of a git pack when the second map comes on top of
  the first. Compute the values for all runs from these numbers.
- [ ] Write the numbers into this plan. Set N, the number of weeks that the history keeps (8.4).

### Phase 1 — the map for the fingerprint tests

- [ ] Set `LLVM_PROFILE_FILE` for each run, reduce the profile to a sparse `.profdata` and the
  function list after the run, and remove the `.profraw` files (8.1).
- [ ] Merge the per-run `.profdata` files of a suite into the suite profile. Make sure that
  `opp_export_coverage` gives the same lcov file as with the `%4m` pool.
- [ ] Make the function table, the emitter table and the include table.
- [ ] Add the NED type closure, the ini section chain and the file trace.
- [ ] Write the map in the layout of 8.3. Add the commands `opp_update_test_map` and
  `opp_show_test_map`.

### Phase 2 — the selection

- [ ] Write the diff reader for diff(A,B) ∪ diff(A,C), with hunks and both sides of each file.
- [ ] Write the rules of section 5 and the always-selected tests of 4.3.
- [ ] Add `opp_select_tests` with `--explain`, and `--changes` on the `opp_run_*_tests` commands.
- [ ] Remove `dependency.py`, `affected_by_modification_filter`, the `dependency_store` field and
  INET `tests/dependency.json`. Before the removal, show the evidence of section 2 that nothing
  uses them.

### Phase 3 — the other suites

- [ ] Statistical (with R-NDEBUG), speed (speed only after omnetpp has `--measure-cpu-usage`,
  section 6).
- [ ] Smoke and sanitizer, after decision D2.
- [ ] The opp tests: per-test profiles and the `.d` files of the test builds; packet as one run.
- [ ] Chart and validation, with the traced process tree.
- [ ] Feature tests (v1 rule).

### Phase 4 — validation

- [ ] Replay (V1) over the last 200 INET master commits. Repair each rule that misses a test.
- [ ] Write the selection ratio for each suite into this plan.

### Phase 5 — CI

- [ ] The weekly coverage workflow writes the per-run profiles and the map. The report job commits
  `map/` to the `master` branch of `inet-framework/coverage` (8.4).
- [ ] The viewer page on `gh-pages`, and links to it from the `genhtml` pages.
- [ ] The shadow check (V2) in the weekly workflow.
- [ ] opp_repl finds and reads the map from the history of `inet-framework/coverage`.
- [ ] opp_ci: a selection option for branch runs.

### Phase 6 — refinements, only where the replay shows a cost

- [ ] R10 v2: generate the `_m` files at both sides.
- [ ] A narrow rule for registrations (R6, R7).
- [ ] I2 v2: section logic for included ini files.
- [ ] H5: instrument omnetpp.
- [ ] Refresh the map for each test that a selected run executes in coverage mode.

## 13. Decisions

- **D1 (decided 2026-11-25)** The map run uses the coverage build that opp_repl has now
  (`-m coverage`), and it is the weekly coverage run. The map goes into the `inet-framework/coverage`
  repository, so that people can browse it (8.4).
- **D6 (decided 2026-11-25)** The weekly run gets the suites that the map needs and that it does
  not run now: statistical, smoke, chart, validation and speed (8.1). The user moved this step into
  phase 0. Speed cannot run now (section 6).
- **D7 (decided 2026-11-25)** The `master` branch of `inet-framework/coverage` can lose old history
  (8.4).

Open:

- **D2** CPU-time limits (7). Recommended: an event limit in omnetpp, and smoke tests with an event
  limit.
- **D3** NED closure: in opp_repl first, or omnetpp change O1 first. Recommended: opp_repl first; O1
  when the failed lookups cost too much (4.3).
- **D4** File trace: `strace` or `LD_PRELOAD`. Phase 0 decides.
- **D5** Maximum age of the map before opp_repl gives a warning.

## 14. Risks

- The per-run profiles can be too slow or too large for the runners. Phase 0 measures this.
- More suites make the weekly run longer. The jobs have a timeout of 150 minutes, and the chart job
  has 240 minutes, because its simulations cannot be split now. If the chart job gets near the
  limit, the split of the chart tests must also divide their simulations (an opp_repl change).
- The map can make the `inet-framework/coverage` repository grow fast. The job drops old history
  (D7). A force push to `master` needs a deploy key that is allowed to do it.
- Wide headers (`Packet.h`, `INETDefs.h`) select almost all tests. This is correct, but such a
  change gets no benefit.
- R6 and R7 are wide, and a new module selects all tests. The replay shows if a refinement is worth
  the work.
- The rules in 4.4 and section 7 are assumptions. V1 and V2 find a defect when an assumption is
  false in practice.
