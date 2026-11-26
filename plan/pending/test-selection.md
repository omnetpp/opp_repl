# Change-based test selection

> **Status:** phases 0-3 done; phase 4 in progress, then phase 5 ·
> **Owner:** opp_repl · **Also changes:** INET (the coverage workflow, the workflows of pull requests,
> `inet.opp`, `run-the-gates.md` and the test rules), the `inet-framework/coverage` repository,
> optionally omnetpp (section 11)

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

This section gives the state before phase 2. Phase 2 removed the old filter (section 12, phase 2).

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
5. A global variable that one translation unit defines and other translation units read does not
   get its value from a header that the readers do not include. Rule R4 finds the code that a header
   change can change, not the data (phase 2).

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
| R3 | A hunk with a line shift (another number of old and new lines), also a code hunk | only the kinds that compare a text output (the opp tests): as R2, for each function below the hunk in the file, because `__LINE__` changes. `__LINE__` goes only into log lines, error messages and the names of static objects (phase 2), so the other kinds do not change |
| R4 | In a `.h` file, outside all function bodies: class definition, declaration, macro, constant, default member value, `#include` | the tests that ran a function f whose emitting TUs all include a changed header. Under the one-definition rule, a TU without a changed header has the same text at both sides, so its copy of f, and so all copies, stay the same. The first version of this rule, the tests of each TU that includes the header, selected all runs for 1983 of 2018 INET headers (phase 2) |
| R5 | Inside a `constexpr` or `consteval` function, or a function with a deduced return type (`auto` without `->`; not a lambda) | as R4 in a header, R6 in a `.cc` file, because the compiler can evaluate the body, or the callers can change with it, and then no counter shows it |
| R6 | In a `.cc` file, outside all function bodies: global data, static members, registration macros (`Define_Module`, `Register_Class`, `Register_Serializer`, and other items), `#include`, `using` | all tests that load the library, because the static initialization of each process runs this code |
| R7 | A new or a removed `.cc` file | all tests that load the library (static initialization) |
| R8 | A new `.h` file | none, because only a changed file can include it, and that file has its own hunk |
| R9 | A removed `.h` file | as R4 |
| R10 | A `.msg` file | v1: as R4 for the generated `_m.h`. The `_m.cc` includes it, and each process runs the constructors of its class descriptors, so v1 selects all tests. v2: generate the `_m` files at both sides and apply R1–R9 to their diff. |
| R11 | Build files: `Makefile`, `makefrag`, `.oppbuildspec`, `.oppfeatures`, `.oppfeaturestate`, the build fields of `inet.opp` | all tests |
| R-NDEBUG | A release-only block (`#ifdef NDEBUG`, the `#else` of `#ifndef NDEBUG`, and the branches of conditionals on macros whose definition depends on `NDEBUG`) names a changed function, or includes a changed file | the runs of the block: the runs of the function that holds it, or of the translation units that include its file (phase 3, `ndebug.py`). For 28f1dc534c no block calls a project function (phase 0), but `INETDefs.h:12` includes `precompiled_release.h`, which the coverage build does not compile |

A hunk that is not fully inside a known function body is "outside all function bodies". This
includes the signature line and the member initializer list of a constructor. This default is
conservative: an unknown place gets the wider rule.

R6 and R7 are wide. A new module class (new `.cc` with `Define_Module`) selects all tests. The
replay (section 10) shows how often this occurs. A later refinement can treat registrations that
other code finds only by name as narrow (R7, phase 6).

**R6 v2 (D10, before phase 5).** A hunk outside the function bodies that holds only complete
function definitions and comments, at both sides, cannot change the static initialization. For
such a hunk:

- a function of side A that the hunk removes or changes selects the tests that ran it (R2);
- a new function selects nothing by itself. Its callers changed, so their hunks select their tests
  (R2), or its declaration is in a changed header (R4).

The hunk keeps R6 if it holds anything else: a declaration outside a function (global data, a
static member, a registration macro, `#include`, `using`), a part that the parser cannot classify,
or a function that runs with no caller (a replacement `operator new` or `operator delete`, a
function with `__attribute__((constructor))`). The measurement for D5 (15.1) found such a hunk in
`Mldv1.cc`: it renames one function and removes another, and R6 v1 selects all tests for it.

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
| N4 | The NED path at C does not load (syntax error, duplicate type, a declared package that does not agree with the folder, as `NedResourceCache::addFile` of omnetpp checks) | all simulation tests, because each simulation loads all NED files |
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
files that INET reads directly. Phase 0 chose the `LD_PRELOAD` library: it costs about 1%, strace
costs about 33%, and it sees the same project files. The NED folder walk of omnetpp lists and
examines all folders of the NED path in each run, so the map leaves the walk out (phase 0).

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
| H6 | A CI file of the project, for INET `.github/workflows/` and `_scripts/github/`; the project gives the path patterns | all tests. Phase 2 gives these files the class "data" and no map record names them, so without H6 they select no test (15.1) |

## 6. The suites

The map records each distinct run once. Two tests that start the same run share one record.

| Suite | Test key | Runs | Map run differs from the test by |
| --- | --- | --- | --- |
| fingerprint | config, run, sim time limit, ingredients | one simulation for the group of ingredient sets of the run | nothing; the map run is the test run of the group, so one record serves all ingredient sets (the `~` ingredients add the computed CRC, checksum and FCS modes, and these change the code that runs) |
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

Three options (D2):

- **D2a.** Make the bound deterministic. Add an event-count limit to omnetpp (O2), and change the
  smoke, sanitizer and feature tests from `cpu_time_limit=1s` to an event limit that is about 1 s on
  the CI machine. The `cpu_time_limit` stays as a safety stop, as in the fingerprint tests. Then the
  map run uses the same bound, and the record is exact.
- **D2b.** Keep the CPU-time limit. The map run uses K × the limit (K=10 by default) and records the
  last event number. The real test also logs its last event number. If a real run gets past the
  recorded event, opp_repl gives a warning and selects the test until the next map. This is correct
  in practice but not proven, because of `finish()` and the destructors. An example from INET:
  before d5418ec4c3 (2026-11-25), `Mldv1::~Mldv1()` called `deleteHeldMessages()` only if a message
  was held at the stop. A map run that stopped when no message was held has no record of that
  function for the test, so a crash in it at the end of the real test is not selected.
- **D2c (decided 2026-11-26).** A fixed `sim-time-limit` for each config, in a store of its own. A
  calibration run measures, for each config, the simulation time that 1 s of CPU time reaches in
  the mode of the smoke tests (debug) on the CI runner, and a command writes the values into the
  store. (Phase 3 changed "release" to the mode of the smoke tests: debug is about 6 times slower
  than release, so a release value would make each debug smoke test about 6 s long.) The smoke,
  sanitizer and feature tests run the same configs (run 0), so they share the store.
  - The tests stop at this simulation time, and the map run uses the same limit. Both stop at the
    same event, so the record is exact, also for `finish()` and the destructors.
  - A larger `cpu_time_limit` stays as a safety stop; the map run has a larger one than the tests,
    because the coverage build is slower. A run that a safety stop ends gives a warning, and the map
    records it with `normal_end` false, so the selection always selects it (4.3).
  - A config without a value (a new config, or a config whose calibration run does not get past the
    initialization) runs with the CPU-time limit of now. The map has no exact record of it, so the
    selection always selects it.
  - omnetpp needs no change: `sim-time-limit` exists, so the event-count limit of D2a (O2) is not
    necessary.

The fingerprint and statistical tests already have a deterministic bound (the sim time limit), so
they do not have this problem.

## 8. The test map

### 8.1 One run, two outputs

The map run and the present coverage report use the same build (`-m coverage`, the
`INET_coverage` library and executable that opp_repl already builds) and the same test runs. Only
`LLVM_PROFILE_FILE` changes:

- Now: `<pool>/%4m.profraw`. The LLVM runtime merges all processes of a suite into 4 files.
- Map run: `<records>/<run id>/profraw/%p.profraw`. Each run writes its own files. Directly after
  the run, opp_repl merges them into a sparse `<pool>/<run id>.profdata` (only the functions that
  ran), reads the function list from it, and removes the `.profraw` files. The other processes of
  a coverage build, for example the config queries of opp_repl, still write into the `%4m` files
  of the pool.

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
| `map/emitter-sets.json` | the sets of more than 20 TUs that emit a function, by id (map version 2, phase 2) |

A set that contains almost all runs is written as "all except ...". Phase 0 measured that this is
enough for the fingerprint map (about 22 MB of text for 1847 runs), but the map of all suites
(about 120 MB) also needs a table of shared run sets: at 200 runs, 15269 functions share 1200 sets.

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
set N = 52 (about 1.3 MB for each week for all suites). A base commit that is older than the oldest kept map
gets no map, and then the selection selects all tests.

A developer can also make a map locally (`opp_update_test_map`).

**The map of each push (D11).** The push run of the fingerprint tests on `master` runs in coverage
mode instead of debug mode. Thus it also makes a map of the fingerprint tests, and it saves the map
as an artifact of the workflow run. A selection takes the map of the newest finished push run whose
commit is an ancestor of B. Without such an artifact (for example, after the retention time of the
artifacts), it takes the weekly map of this section. The weekly map stays for the viewer, and for
the kinds that the push runs do not run in coverage mode.

### 8.5 Reverse queries

`opp_show_test_map` answers "which tests used this file, function, NED type or ini section", "what
did this test use", and gives the summary for each folder. It reads the same files as the viewer.

## 9. The selection

**Commands.**

- `opp_select_tests -p inet --changes <rev | rev..rev | rev...rev | worktree | patch file> [--map <folder>]
  [--kind <kind>...] [--explain] [--summary] [--json]` prints the selected tests of each kind. `--explain` gives the rule
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
6. Give the map commit, its date, and the number of tests that the A..B side alone selects. This
   number is the cost of the age of the map (D5). If the map is older than 2 days, give a warning:
   with the maps of the push runs (D11), such a map means that the push runs make no maps, or that
   opp_repl did not find the newest map.

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
- **V4 Check of each push.** A push to `master` runs all tests (15.3). Then it computes the
  selection for `github.event.before..github.sha`. Each test whose outcome differs from the
  previous push run must be in the selection. If one is not, the job fails and names the test, the
  commit and the rules.

## 11. Proposed omnetpp changes

All are optional. Each one removes a workaround in opp_repl.

| Id | Change | Without it |
| --- | --- | --- |
| O1 | The usage collector also prints the base types, the interfaces and the failed lookups of NED types, with the file of each declaration | opp_repl computes the closure from the NED sources; failed lookups stay unknown (4.3) |
| O2 | An event-count limit config option | not necessary: D2c uses `sim-time-limit` (section 7) |
| O3 | Print the included ini files of a run | the file trace gives them |

## 12. Steps

The order of the phases (D8): phases 4 and 5 for the fingerprint tests come before phase 3. Then
phase 3 adds one kind at a time, and each kind goes through the replay of phase 4 and the jobs of
phase 5 before the next kind starts.

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
  `inet-coverage-more-suites`), pushed to `origin` on 2026-11-25 without a pull request.
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
- [x] Run the workflow of the branch on GitHub, and record the job times. The manual run
  45618369076 (INET 0798401b78) passed in all 11 jobs in 91 minutes.
  - Job times (each job includes about 32 minutes to compile INET), with the test time in
    parentheses: fingerprint 29 to 42 minutes (10 to 17), suites 47, statistical-0 44 (25),
    statistical-1 55 (28), chart 90 (71), smoke 36 (10), validation 41 (3), report 1. Coverage
    mode is about 3 times slower than release mode for the statistical tests and about 5 times
    slower for the chart tests, not 6 times. The chart job used 90 of its 240 minutes.
  - Report: lines 68.75% (+0.58), functions 68.87%, branches 58.26%. Lines for each new suite:
    statistical 58.87%, smoke 58.16%, chart 20.76%, validation 7.09%.
  - Three suites gave a warning with exit code 1. The coverage data of the three suites is
    complete:
    - module: `Lan80211MobilityIndependence_1` and `Ieee80211BlockAckVariant_1` FAIL. Both tests
      start `bin/inet --debug`, and the coverage job has no debug build. The master run
      45588176059 has the same 2 failures. Both tests pass in `module-tests.yml` (debug).
    - statistical-1: `tutorials/protocol -c Network7` FAIL, also locally in coverage mode. Only
      `Network7.server.app` differs: release gets 3 packets, coverage gets 0. The cause is an
      INET defect: `Reordering::expectedSequenceNumber`
      (`src/inet/protocolelement/ordering/Reordering.h`) has no start value. In release, the
      value happens to be 0, so the stored baseline records undefined behavior.
    - smoke: 8 runs `PASS (unexpected)` against an `#expected-result = "ERROR"` marker. For
      `examples/inet/nclients` (3 lwIP configs) and `showcases/visualizer/osg/earth` (3), the
      markers assume the default features, but `_scripts/github/build-inet.sh` enables all
      features. For `DynamicIPv6` of `examples/manetrouting/dymo` and `gpsr`, the reason is not
      known. The markers come from a7d373ce7b (2022), and no release run of the smoke tests
      exists for comparison. No other GitHub workflow runs the smoke tests.
  - Repairs (2026-11-25, local, not pushed):
    - module: INET 6921020a07 on `topic/coverage-more-suites` removes `--debug` from the two
      tests, and opp_repl f5801f3 gives the test program `MODE` of the run. Both tests pass in
      coverage mode with `MODE` unset.
    - statistical: INET c5d48a5cb4 on the branch `topic/reordering-expected-sequence-number`
      gives `expectedSequenceNumber` the start value 0. Network7 passes in debug and release, and
      the fingerprints of `tutorials/protocol` do not change.
    - smoke: INET 0af9da9b1e on `topic/coverage-more-suites` removes the 8 wrong markers
      (`examples/inet/nclients` lwIP ×3, osg/earth ×3, dymo and gpsr `DynamicIPv6`). The lwIP
      markers recorded an error that the configs had also with TcpLwip built. Now the
      fingerprint store on master records PASS for them. With TcpLwip off they give ERROR,
      the same as the 8 lwIP configs of `bulktransfer` and `tcpclientserver`, which have no
      marker.
The measurements below ran on 2026-11-25 on this machine (32 cores, clang 23), with the coverage
build of the worktree `inet-coverage-more-suites` (INET 28f1dc534c, all features, omnetpp-6.x in
coverage mode). The prototype scripts are in `plan/pending/test-selection/`: `capture.py` (the
command lines of fingerprint runs), `measure.py` (times and profiles), `filetrace.c` (the
`LD_PRELOAD` trace), `tracecmp2.py` (strace against `LD_PRELOAD`), `maprun.py` (the map run) and
`mapwrite.py` (the map in the layout of 8.3).

- [x] Build INET with `-m coverage`. Run 20 fingerprint tests, each with its own `LLVM_PROFILE_FILE`.
  - The 20 tests are the test with the median time in 20 folders with many tests (from
    `examples/wireless` to `examples/sctp`). All 20 runs verified their fingerprints.
  - `capture.py` takes the command lines from opp_repl without a run (a `simulation_runner_class`
    that records them). It must apply the defaults of `inet.opp`
    (`apply_project_test_defaults("fingerprint", ...)`: `stored_only`, `select_fingerprint`,
    `ingredients_list`, `cpu_time_limit`). Without them, opp_repl makes the tasks with the sim time
    limit of the ini file, and 4 of the 20 tests skip with "Correct fingerprint not found". With them,
    INET has 1847 fingerprint runs.
  - `<run id>/%p.profraw` is correct. Seven modules of a run are instrumented (`opp_run_coverage`,
    the omnetpp libraries and `libINET_coverage.so`). With `%p`, all seven write into the same file
    (95331 functions = the sum of the 7 modules with `%m`), so no data is lost.
- [x] Measure: size of one `.profraw`, time to reduce it to the functions that ran
  (`llvm-profdata merge -sparse` and `show --all-functions`, or `show` on the raw file), the
  number of functions in the binary, functions for each run.
  - One `.profraw` for each run, 23.8 MB for each run (counters of all 95331 functions).
  - `merge -sparse`: 0.32 s, result 1.2 to 2.1 MB (median 1.6 MB). `show --all-functions` on the
    sparse file: 0.014 s. `show --all-functions` on the raw file: 0.28 s. Both give the same list.
  - A merge of the 20 sparse files into a suite profile: 0.08 s, 3.4 MB.
  - Functions: 95331 in the 7 modules, 76591 in `libINET_coverage.so`, 75930 of them in INET
    sources. For each run, 8074 to 13204 functions ran (median 11208, omnetpp functions included).
    In the 20 runs together, 15657 INET functions ran (20.6%).
- [x] Measure the overhead of `strace -f -e trace=%file` and of an `LD_PRELOAD` trace on the same
  20 runs. Examine if `strace` works in the podman and GitHub containers.
  - Wall time against the mean of two plain runs: `strace` +33% (median, range 6% to 49%; the
    sum of the 20 runs 25.9 s → 31.0 s). `LD_PRELOAD` +1% (median), which is below the
    difference of the two plain runs (1.7%).
  - Completeness, compared on the real paths in the INET tree: both traces have the same 19261
    folders. The `LD_PRELOAD` trace has all project files of the strace except two kinds: about
    600 library lookups of the dynamic loader in the working directory of each run, and `readlink`
    calls on path components inside glibc `realpath` (the trace has the full path of the
    `realpath` call). The library lookups occur because `get_env` gives
    `LD_LIBRARY_PATH=<omnetpp>/lib:` with an empty entry, which means the working directory. The
    build rules (R11) cover shared libraries.
  - The trace library needs these hooks: `open`, `open64`, `openat`, `openat64`, `__open_2`,
    `fopen`, `fopen64`, `stat`, `lstat`, `fstatat`, `statx`, `access`, `faccessat`, `opendir`,
    `readlink`, `realpath`, `glob`, `chdir` and `fchdir`. omnetpp walks the NED folders with
    `chdir` and `glob("*")` (`FileGlobber`, `src/common/fileglobber.cc`), and `glob` opens the
    folders inside glibc, so the library records the `glob` call and follows `chdir`. It writes
    physical paths: `showcases/*/doc/media` are links into the `media` baseline checkout.
  - The GitHub test jobs run on the `ubuntu-latest` machine, not in a container. The
    `LD_PRELOAD` trace works in the rootless podman image `ghci-ci:26.04`. That image has no
    strace, and I did not install one.
  - Decision: the map run uses the `LD_PRELOAD` trace. It costs nothing measurable and is complete
    for project files, so strace is not necessary.
- [x] Measure the time of `llvm-cov export` for the function table and of `nm` over all objects.
  - `llvm-cov export -format=text -skip-expansions` of `libINET_coverage.so`: 94 s, 1.8 GB of
    memory, 65 MB of JSON. (Phase 1 found that 92 s of this time were lookups on the debuginfod
    server; without `DEBUGINFOD_URLS` the export takes 1.9 s.) It lists all 76591 functions, also those with count 0. The code
    regions of file 0 give the line range of the body.
  - `nm --defined-only -A` over the 1791 objects: 11.1 s, 549 MB of output. With 8 parallel
    processes 1.65 s, but each process needs its own output file: with one shared output, the
    lines mix.
  - The `.d` files give their paths relative to `src/`, because `make` runs there.
- [x] List the release-only blocks in the 15 `NDEBUG` files. There are 5:
  `INETDefs.h:12` (the precompiled header), `ModuleRefByGate.h:43` and `ModuleRefByPar.h:46` (a
  shorter `cRuntimeError` message), `Chunk.h:34` (`CHUNK_CHECK_USAGE_ENABLED 0`) and
  `TcpSackRexmitQueue.cc:547` (an early return). The `#else` parts of the macros that depend on
  `NDEBUG` (`DEBUG_CHECK_IMPLEMENTATION` in `DebugDefs.h:168`, `CHUNK_CHECK_USAGE` in
  `Chunk.h:43`) call no more functions than the debug parts. No release-only block calls a project
  function, so the R-NDEBUG list is empty for 28f1dc534c, and release mode runs a subset of the
  functions of coverage mode. The map run keeps the scan, because a new block can come.
- [x] Write the map of the 20 runs in the layout of 8.3 for two INET commits one week apart.
  Measure the size of each map, and the growth of a git pack when the second map comes on top of
  the first. Compute the values for all runs from these numbers.
  - Commits: bc39ec7571 (2026-11-17) and 28f1dc534c (2026-11-25), 141 commits apart. A second
    sample has 200 runs (the 20 runs and 180 random runs, seed 1) at both commits.
  - The map run (`maprun.py`) gives each run its profile, the `LD_PRELOAD` trace,
    `--print-instantiated-ned-types=true` (`src/sim/csimulation.cc:72`) and
    `-q sectioninheritance` (0.18 s for each run, because the process loads the 1 GB library;
    phase 1 can read the chain from the ini file in Python instead).
  - The run id is the first 8 hex digits of the SHA-1 of `"fingerprint " + <test name>`.
  - Map content (`mapwrite.py`): for each function body, the line range, one demangled name, the
    run ids and the TUs that emit it (when they differ from the file itself); `tu_runs` for each
    TU; `included_by` for each header; NED types; ini sections; data files. A type of a `types:`
    section belongs to the file of its outer type. `ned.IdealChannel` and `ned.DatarateChannel`
    are omnetpp types and stay unresolved.
  - File trace in the map: in all runs, the only folder listings are the NED walk of omnetpp
    (`glob("*")` in 963 to 988 folders for each run), and INET code lists no folder. The walk also
    examines each entry with `stat`. The map drops the walk, the successful `stat` calls in walked
    folders and the failed lookups of broken links (for example `doc/media` without the `media`
    checkout). It keeps reads and examinations of files that git tracks, and failed lookups of
    any path in the tree. Rule F2 thus applies only to `opendir` and `O_DIRECTORY` listings, and
    N2 covers the NED walk.
  - Sizes:

    | Runs | Map files | Text | `tar.gz` | Git pack, first map | Growth for one week | Files changed |
    | --- | --- | --- | --- | --- | --- | --- |
    | 20 | 4497 | 14 MB | 1.67 MB | 1973 KB | 125 KB | 197 |
    | 200 | 5022 | 17 MB | 1.87 MB | 2307 KB | 146 KB | 219 |

  - The run lists grow by about 1000 run ids for each run (22456 ids for 20 runs, 204421 for 200
    runs), that is about 12 KB of text for each run. The functions that ran share few distinct run
    sets: 300 sets for 10910 functions (20 runs), 1200 sets for 15269 functions (200 runs). The
    largest map file has 200 KB at 200 runs (`SctpHeader_m.cc.json`).
  - The map writer needs 15 s for 20 runs and 64 s for 200 runs (Python set operations), and
    0.8 GB of memory. Phase 1 must make it faster for all suites.
  - Values for all runs, linear in the number of runs from the two samples: for the 1847
    fingerprint runs, a pack of about 5.4 MB, about 0.34 MB for each week, and about 22 MB of run
    lists in the text. For about 10000 runs of all suites, about 20 MB, about 1.3 MB for each week
    and about 120 MB of text. With the larger text, the largest files grow to some MB. So "all
    except" is enough for the fingerprint map, but the map of all suites needs the table of shared
    run sets (8.3).
  - Map run cost for each run: 0.33 s for the profile, about 1% for the trace, and 0.18 s for the
    section query. For the 1847 fingerprint runs, that is about 15 minutes of CPU time.
  - Error of the prototype: `capture.py` records the first task of each fingerprint group
    (`tplx`) alone. The real test runs the group in one run, with all ingredient sets
    (`--fingerprint 7935-71f1/tplx,0000-0000/~tNl,0000-0000/~tND`), and the `~` ingredients add
    `--fingerprintcalculator-class=inet::FingerprintCalculator` and `--**.crcMode="computed"
    --**.checksumMode="computed" --**.fcsMode="computed"`. So the map runs of phase 0 did not run
    the computed CRC, checksum and FCS code, nor the INET fingerprint calculator. In 198 of the
    200 runs the `tplx` fingerprint is the same; in `tutorials/protocol -c Network4` and
    `-c Network6` the computed FCS changes the trajectory, and the fingerprint does not match.
    Through opp_repl, both pass in coverage, debug and release mode. The sizes and times above
    change only a little, but the counts of functions for each run are a little too low. Phase 1
    must run each group as the test runs it.
  - One run of bc39ec7571 (`showcases/wireless/sensornetwork -c StatisticLMac`) stops with exit
    code 1 in the prototype run. I did not examine it.
- [x] Write the numbers into this plan. Set N, the number of weeks that the history keeps (8.4).
  N = 52: with about 1.3 MB for each week for all suites, a year of history is about 90 MB.

### Phase 1 — the map for the fingerprint tests

Phase 1 works in the opp_repl worktree `opp_repl-test-map` (branch `topic/test-map`). The checks
ran on the coverage build of the worktree `inet-coverage-more-suites` (INET 28f1dc534c and two
commits that change only tests and ini files).

- [x] Set `LLVM_PROFILE_FILE` for each run, reduce the profile to a sparse `.profdata` and the
  function list after the run, and remove the `.profraw` files (8.1).
  - `opp_repl/test/test_map/record.py`: the option `--test-map-records FOLDER` of
    `opp_run_fingerprint_tests` (`run_fingerprint_tests(test_map_records=...)`, only with
    `-m coverage`) gives the run the simulation runner `TestMapSimulationRunner`. The runner runs
    the process as the subprocess runner does, with its own `LLVM_PROFILE_FILE`, the trace library
    in `LD_PRELOAD` and `--print-instantiated-ned-types=true`. So the map run is the test run: the
    fingerprint group runs with all its ingredient sets, and the test checks the same output.
  - The run key is `<kind>:<ini path>:<config>:#<run>:<sim time limit>`, and the run id is the
    first 10 hex digits of its SHA-1. With 8 digits, 10000 runs have a collision with a
    probability of about 1%; with 10 digits, about 0.005%.
  - The record `<records>/<run id>/` has `run.json` (the key, the parameters, the exit code, the
    end of the run, the NED types and the section chain), `functions.txt.gz` (about 93 KB for
    12700 functions) and `files.txt`. The runner writes `run.json` last.
  - The end of the run is the last `<!>` line with an event number. The fingerprint lines come
    after the stop line and have no event number.
  - The trace library now writes `write` for an open that only writes or truncates. The record
    leaves out these outputs and all paths in the result folder of the run. Before this change, the
    `.rt` and `.elog` files of `results/` were reads and lookups.
  - The section query runs once for each ini file and config in a process, with the profile to
    `/dev/null`.
  - Self tests: `opp_repl/test/self/test_map.py` (15 tests, also the trace library on a real
    process).
- [x] Merge the per-run `.profdata` files of a suite into the suite profile. Make sure that
  `opp_export_coverage` gives the same lcov file as with the `%4m` pool.
  - `merge_coverage_profiles` merges the `.profdata` files of the pool too (opp_repl 578ad7a).
  - Checked: the 24 fingerprint runs of `examples/manetrouting`, once without and once with
    records, give the same lcov file (11.2 MB, `cmp` finds no difference). The wall time of the
    test is 20.0 s without and 20.3 s with the records.
- [x] Make the function table, the emitter table and the include table.
  - `opp_repl/test/test_map/build.py`: `make_test_map_build_tables` gives the three tables of the
    coverage build as one gzip JSON file (3.6 MB for INET): 75930 functions with file and body
    lines, 27074 emitter entries (only the functions whose translation units are not only their own
    source file), and the headers of 1773 translation units. It takes 10 s and 1.8 GB of memory
    (the JSON of the export).
  - `llvm-cov` asked the debuginfod server (`DEBUGINFOD_URLS`, set by Ubuntu) for each binary, and
    each export took 95 to 160 s with less than 2 s of CPU time. opp_repl 1e39d6c starts
    `llvm-cov` without the variable. This also makes `opp_export_coverage` faster: 2.7 s instead of
    93 s for 24 runs, with the same lcov file.
  - The emitter table reads the profile counters (`__profc_<name>`, with the characters
    `-:;<>/"'` of a local name replaced by `_`), not the code symbols (`T`, `t`, `W`). With the
    code symbols, 1323 header functions that ran in the 24 runs of `examples/manetrouting` had no
    emitter, for example the `C2` constructors of `IntrusivePtr`: the objects hold their code and
    their counter, but no symbol of that name. With the counters, no function that ran is without
    an emitter. 2635 header functions have no emitter: no object holds their code, and they did
    not run. A sample of 200 source functions without an entry has its counter in the object of
    its own file.
  - The function name of the coverage mapping is the name in the profile, so the functions of a
    record match the table directly. A function with internal linkage has the name
    `<file>:<symbol>` (1307 functions).
- [x] Add the NED type closure, the ini section chain and the file trace.
  - The section chain and the file trace are in the records (item 1).
  - The build tables have a NED type table: `opp_nedtool c -x -m` converts the NED folders of the
    project to one XML file (0.16 s), and `read_ned_type_table` gives for each of the 2008 INET
    types its file and the types that it refers to: `extends` and `like` of the declaration, and
    the `like` interfaces of its submodules and connections. The names resolve with the rules of
    `NedResourceCache::lookupNedType` of omnetpp, in the same contexts (the parent for the
    declaration, the compound module or its top-level type for the body). For a wildcard import,
    omnetpp takes the first match, so the table takes all matches. Only the built-in omnetpp types
    `DatarateChannel` and `ned.DatarateChannel` stay unresolved.
  - `get_ned_type_closure` adds the references to the instantiated types of a run, recursively.
    In the 24 runs of `examples/manetrouting`, 60 to 75 instantiated types give 171 to 191 types.
    Each instantiated type is in the table, except the omnetpp type `ned.IdealChannel`.
  - This is the recommendation of D3 (the closure in opp_repl first). omnetpp change O1 is still
    open.
- [x] Write the map in the layout of 8.3. Add the commands `opp_update_test_map` and
  `opp_show_test_map`.
  - `opp_repl/test/test_map/writer.py` (`write_test_map`, `update_test_map`) and `show.py`
    (`show_test_map`), opp_repl c72a01c; the guide is `doc/test_map.md`. Run sets are Python
    integers used as bit sets, and each distinct set is converted to text once.
  - `opp_update_test_map` removes the old records of its records folder (and refuses a folder
    with other files), runs the fingerprint tests with records, makes the build tables and writes
    the map. With `--no-run` and more than one `--records`, it writes the map of the records of
    other runs, for example of the CI splits. It does not remove a map folder that holds no
    `header.json`.
  - The header has the map commit and `changed_files` (a tree with changes), the omnetpp commit,
    the opp_repl commit (from git, because `_version.py` can be old), the compiler, the enabled
    features and the date.
  - The full map of 28f1dc534c (all fingerprint tests, coverage build, 32 cores): 1847 runs,
    1846 tests PASS and 1 ERROR (expected), 6 min 50 s for the tests and 438 s in total; build
    tables 10 s; map writer 6 s, with 2 GB of memory for the whole command.
  - Map: 6438 files, 45 MB of text, 4.4 MB as `tar.gz`, a git pack of 3.8 MB (phase 0 predicted
    5.4 MB). The largest map file is `Ieee80211VhtMode.cc.json` (1.5 MB), then `runs.json`
    (0.9 MB). 57087 function bodies, 19986 of them ran; 1317 NED files, 306 ini files and 651
    data files; 4726 fingerprint tests in `tests.json`.
  - Records: 173 MB (146 MB of them the function lists, 7894 to 14981 functions for each run,
    median 11087). The per-run profiles in the pool: 2.9 GB. Phase 5 must keep these sizes in mind
    for the CI artifacts.
  - The only run with `normal_end` false is the expected ERROR
    (`tests/fingerprint/ethernet-nonstandardspeed.ini`, exit code 1). Its run number is an
    iteration filter, so its key is
    `fingerprint:tests/fingerprint/ethernet-nonstandardspeed.ini:General:#$datarate==5Gbps   && $duplex==false:5s`.
  - Checked: 300 random function bodies that ran have exactly the runs of the records; the 35 self
    tests pass.
  - The growth for one week was not measured for the full map; it needs the map of a second commit
    (phase 0 measured 125 to 146 KB for 20 and 200 runs).

### Phase 2 — the selection

Phase 2 works in the opp_repl worktree `opp_repl-test-selection` (branch `topic/test-selection`,
from main f6d900a). The checks use the map of version 2 that the phase 1 records give
(`opp_update_test_map --no-run`, 8 s), and a scratch INET worktree at the map commit 0af9da9b1e.

- [x] Write the diff reader for diff(A,B) ∪ diff(A,C), with hunks and both sides of each file.
  - `opp_repl/test/test_map/changes.py` (opp_repl 96f319a): `git diff -U0 --no-renames` (a rename
    is a removal and an addition), the text of each side from git or from the working tree, and
    the untracked files of the working tree as added files. `Changes` gives B and C for
    `worktree`, a commit (B is its first parent), `rev1..rev2`, `rev1...rev2` (rev2 can be
    `worktree`) and a patch file. A patch goes into a temporary index on `HEAD`
    (`git apply --cached`, `git write-tree`), so the index and the working tree do not change.
  - When A = B, the selection reads only diff(A,C).
- [x] Write the rules of section 5 and the always-selected tests of 4.3.
  - `opp_repl/test/test_map/select.py` (opp_repl ea88342). A lexer gives the tokens of each line
    without comments and white space (white space stays a token between two punctuation
    characters and in a directive). A hunk is trivial (R1) if its old and new tokens are the
    same and no line outside the hunks changed its tokens (an opened comment).
  - The body of a function in the map is the line of `{` to the line of `}`, so a hunk on the
    signature line or on a line of a brace is outside the body.
  - R4 changed: the rule of the plan selected all runs for 1983 of 2018 headers, because 1626 of
    1710 TUs have all runs: inline functions that run in each process are in almost all TUs.
    The new rule (5.1) needs all emitting TUs of each function, so the map has version 2 with
    `emitter-sets.json` (opp_repl fa0933d, 367 sets, 2.3 MB). For each header of INET alone: 620
    headers select all runs, 248 select none, and the median header selects 253 of 1847 runs.
    With only the number of more than 20 emitters (version 1), 732 headers select all runs.
  - The remaining all-run headers come from the static initialization of the TUs that include
    them: the constructors and destructors of the generated class descriptors (each `_m.cc`),
    the serializer registrations, the static mode tables of 802.11, and value types such as
    `Ipv4Address` and `ClockTime` in static objects. Without the descriptors, 361 headers select
    all runs (phase 6).
  - R3 changed: the opp tests only (5.1). A new statement in `Ipv4::handleIndication` then
    selects 105 instead of 2994 of 4726 fingerprint tests.
  - N4 also checks the declared package of each new or changed NED file against the package
    that omnetpp expects (the package of `package.ned` in the root of the NED folder, and the
    folders below it). All 1655 NED files of INET in the NED folders agree.
  - The environment check (4.3) compares the header of the map with this environment. The
    opp_repl and omnetpp commits count as the same if their diff changes only documentation,
    plan files, `opp_repl/test/test_map/` and the self tests.
  - Checked on the full map, one change for each rule (`--changes worktree` in the scratch
    tree, each 0.1 to 0.7 s): a comment selects 0 tests; a changed string literal in
    `handleIcmpErrorIndication` 105 (R2, 39 runs); an `#include` all (R6); a new member in
    `Ipv4.h` 3003 (R4, 1045 runs); `timeToLive` in `Ipv4.ned` 2994 (N1, 1042 runs); a new type
    `inet.foo.Ipv4` 2994 (N2); a second `inet.networklayer.ipv4.Ipv4`, a NED syntax error and a
    wrong package all (N4); a changed section of `examples/ethernet/lans/omnetpp.ini` 2 (I1),
    a new section 0, an iteration variable in `General` 2 (I3); a data file 3 (F1); a comment in
    `Ipv4Header.msg` all (R10); `.oppfeatures` all (R11); the statistical baseline pin in
    `inet.opp` 0 fingerprint tests (E5); one store entry 1 (E1). The 3 tests of the run that did
    not end normally come on top of each number.
  - Self tests: `opp_repl/test/self/test_selection.py` (28 tests, also the rules on a small map in
    a git repository).
- [x] Add `opp_select_tests` with `--explain`, and `--changes` on the `opp_run_*_tests` commands.
  - opp_repl 9cda698. All `opp_run_*_tests` commands take `--changes`, `--test-map` and
    `--ignore-environment`. `run_fingerprint_tests` keeps the selected tests of each group of
    ingredients, and `run_all_tests` does so for its fingerprint tests. The other kinds run all
    tests, and the command says so. `--changes` with `--test-map-records` is an error.
  - Checked: a dry run of the fingerprint tests of INET with the changed string literal as a
    patch selects 105 of 4726 tests, the same as `opp_select_tests`, so the keys of the test
    tasks are the keys of the map.
  - The guide is the section "Select tests" of `doc/test_map.md`.
- [x] Remove `dependency.py`, `affected_by_modification_filter`, the `dependency_store` field and
  INET `tests/dependency.json`. Before the removal, show the evidence of section 2 that nothing
  uses them.
  - Done 2026-11-26, after the user agreed: opp_repl 5d46ac3 removes the code, the parameters and
    the line of `doc/opp_files.md`. INET de20ccae69 removed `tests/dependency.json` on a local
    branch; on 2026-11-26 it was rebased and put on the local `master` as b79190d7e5. The 165 tests of
    `opp_run_self_test` pass, and the dry run of the fingerprint tests with `--changes` again
    selects 105 of 4726 tests.
  - One more user came up before the removal: the workspace file
    `inet-master+omnetpp-6.x.opp` (2026-05-07, not in git) sets
    `dependency_store="tests/dependency.json"`. `SimulationProject` takes `**kwargs` and ignores
    an unknown parameter, so the file loads as before. The dead line was removed from the file.
  - The evidence (2026-11-25), shown to the user before the removal:
    - opp_repl 2a08716 (2026-04-29) added `opp_repl/simulation/dependency.py` (197 lines) and
      `affected_by_modification_filter`. Its users are only `opp_repl/simulation/__init__.py`
      (`import *`), `get_simulation_tasks` (`opp_repl/simulation/task.py`, the parameter and 15
      lines), the `dependency_store` field of `SimulationProject` (`project.py`) and one line of
      `doc/opp_files.md`. No command, test or other module calls them.
      `opp_repl/test/self/dependency.py` tests the optional Python packages, not this code.
    - opp_ci, opp_env, opp_dev, inet-gpl and INET (`python/`, workflows) do not use them.
    - INET cb9d11aab7 (2026-05-07) added `tests/dependency.json` (17229 lines); three commits of
      2026-06-12 to 2026-06-17 (for example 88098c2146) removed the entries of removed examples.
      `inet.opp` does not set `dependency_store`, so no code reads the file.

### Phase 3 — the other suites

The work goes in the worktree `opp_repl-test-selection` (branch `topic/test-selection`), one kind
at a time. Each kind gets: records from its run command (`--test-map-records`), its test keys in
`tests.json`, the filter of its tasks for `--changes`, its rules for expected results, self tests,
and a check on a real INET map with the scenarios of phase 2.

- [x] The kinds in general: one function applies `--test-map-records` and `--changes` to the
  tasks of any simulation test kind, `run_fingerprint_tests` uses it too, and
  `opp_update_test_map --kind` makes the map of more than one kind.
  - opp_repl 40eaa3d: `apply_test_map_options()`, `get_test_key()`, `select_test_tasks()` for
    any task list, `TEST_MAP_RUN_FUNCTIONS`. `run_all_tests` used the name of a task list
    (`statistical test`) as the kind, so it never found these tests in the map; `get_test_kind()`
    repairs it.
- [x] Statistical (with R-NDEBUG). Speed is still not possible (section 6).
  - The records: the 945 statistical tests of INET 0af9da9b1e in coverage mode on 32 cores in
    12 minutes: 933 PASS, 11 SKIP (interactive configs), 1 FAIL (`tutorials/protocol` `Network7`,
    the Reordering defect that INET c5d48a5cb4 repairs on another branch). The map of the
    fingerprint records of phase 1 and these records: 2791 runs, 85 MB of text, 21 s to write.
  - The keys: the 945 statistical tasks and the 944 statistical tests of the map agree; the one
    task without a record (`showcases/ethernet/tenbaset1s` `General`, no sim time limit) did not
    run, and the selection always selects it.
  - The check whether a config is interactive starts the simulation, so the 11 interactive configs
    have records that did not end normally (10 in the map). The selection always selects them, and
    the run skips them.
  - Scenarios on this map: the string literal of phase 2 selects 105 fingerprint and 41
    statistical tests (the dry run of `opp_run_statistical_tests`: 42 of 945, with the task
    without a record); the new member of `Ipv4.h` selects 3003 fingerprint and 730 statistical
    tests.
  - E2 (opp_repl 4cdfa34): a move of the `statistics` pin selects the tests whose `.sca` file
    differs between the two pins. Without the two commits in the `statistics` checkout, it selects
    all statistical tests. Checked: the move between the pins e4517d35 and 323dd063 (INET
    617ce3bad0) changes 2 result files, and E2 selects exactly their 2 tests.
  - R-NDEBUG (opp_repl a39dc37): the map writer scans the C++ files (`ndebug.py`), and the map
    (version 3) holds `release-only.json`. The scan evaluates each conditional for release and
    debug, also through macros that depend on `NDEBUG`, and takes an `#ifndef X` whose branch
    defines X as a guard. For INET it finds the 5 blocks and the 2 `#else` branches of macros of
    phase 0. No INET function has a name of a block (the parameters of a macro are left out). A
    new `#include` in `precompiled_release.h` now selects all 1847 runs; before, it selected none.
- [x] Smoke and sanitizer, with the bound of D2c (section 7): the store of the simulation-time
  limits, the calibration run, and the command that writes the store. The `#expected-result`
  comments of the ini files are expected results of the smoke tests. The ini rule ignores comments,
  so they need their own rule, as E1 for the store (phase 2: INET 0af9da9b1e changes only these
  comments).
  - I4 (opp_repl 8982bce): opp_repl reads `#expected-result`, `#abstract`, `#emulation` and
    `#bounded` also from comments, so they are entries of their section, for all kinds. INET
    0af9da9b1e now selects the tests of its 8 configs (20 fingerprint, 8 statistical, 8 smoke and
    8 sanitizer tests) and the tests that are always selected; before, it selected none.
  - D2c (opp_repl 5b2ef0d): `test_parameters["smoke"]["sim_time_limits"]` names the store, and
    `opp_update_smoke_test_sim_time_limits` writes it. A value stops the smoke, sanitizer and
    feature tests at that simulation time, with a safety CPU-time limit of 30 s; `null` is a run
    that ends by itself; a config without a value keeps 1 s of CPU time. A run that a CPU-time or
    real-time limit stopped is no longer a normal end, so the selection always selects it. A smoke
    record is also the run of the sanitizer test of its config. `test_parameters` accepts only
    known keys (`RECOGNISED_TEST_ASPECTS`), so `sim_time_limits` is one now, and INET needs this
    opp_repl.
  - INET 038e4a5a20 on the local branch `topic/smoke-sim-time-limits` (from `master`
    b79190d7e5): `tests/smoke/sim-time-limits.json` from a calibration at 0af9da9b1e on 32 cores in
    coverage mode (about as fast as debug), 931 values: 412 times and 519 null; 3 configs do not get
    past the initialization in 1 s. A calibration on the CI runner replaces it (phase 5).
  - Checked: the calibration of the 945 smoke tests needs 1:36; with the store, the 945 tests with
    records need 2:05, 934 pass, 11 interactive configs are skipped, and each run stops at its
    limit. The keys of the 945 smoke and the 945 sanitizer tasks agree with the map. On the map of
    3736 runs: the string literal of phase 2 selects 43 smoke and 43 sanitizer tests, the new member
    of `Ipv4.h` 731 of each, a comment 14 (the tests that are always selected).
- [x] The opp tests: per-test profiles and the `.d` files of the test builds; packet as one run.
  - opp_repl f143e9d: `TestMapRecorder` writes the record of one run of any test. An opp test and
    the packet test give the processes of their run its environment; the record has `includes`,
    the project files that the own code of the test includes (from the `.d` files). Keys:
    `<kind>:<path of the .test file>`, `packet:tests/packet`. The map gives each such file
    `test_runs`, so R4 selects these tests, also for a header outside the C++ folders (any change).
    E6: a changed `.test` file selects its test. H4 (v1): a change below the support library of a
    kind (`lib_folder`, else `<test_folder>/lib`) or the folder of a binary test selects all tests
    of the kind.
  - opp_repl 999ffd9: `--print-instantiated-ned-types` writes into the standard output, which the
    opp tests compare, and 10 TCP module tests failed with records. A wrapper of the test program
    moves these lines into `ned-types.txt`. A `%testprog` program can be another program, so its
    record has no NED types and no normal end: the 306 packetdrill tests of `tests/protocol`
    (`inet_run_packetdrill`, skipped without packetdrill) are always selected.
  - Checked on INET 0af9da9b1e in coverage mode, with records: unit 154 tests in 3:05, all pass;
    module 846 in 2:13, all pass; queueing 77 in 0:13; protocol 1198 in 2:24 (847 pass, 306
    skipped and 45 expected failures, as without records); packet 1. A new declaration in
    `CanvasProjection.h` selects 7 unit tests.
- [x] Chart and validation, with the traced process tree.
  - opp_repl eb50c0e: the simulations of the chart tests write records (kind `chart`), and the run
    writes `chart-tests.json`, the run keys of the simulations of each chart test; the key is
    `chart:<.anf file>:<chart id>`. With `--changes`, only the simulations of the selected chart
    tests run. The chart code runs in the opp_repl process, so no trace: H3 (a changed `.anf`
    file selects its chart tests), H2 (a change in the Python folders of the project selects all
    chart and validation tests), E3 (a moved `media` pin selects the chart tests of each folder
    with a changed image), and the map header records the versions of matplotlib, numpy, pandas
    and scipy (another version selects all chart tests). The validation tests are a kind without
    records, as the feature tests; `run_validation_tests` runs all or none.
  - Checked with the 10 chart tests of `showcases/wireless/coexistence` and `qos` (all pass in
    coverage mode): the `media` pin move of 42dbb75bfb selects the 8 QoS chart tests, a change of
    `Coexistence.anf` its 2 tests and only their 24 simulations, a change of
    `python/inet/scave/plot.py` all chart and validation tests.
  - The map of all kinds (6038 runs, 167 MB of text, 19 s to write), for each scenario the
    selected tests (fingerprint of 4726; the other kinds, and the opp tests include the 351 protocol
    tests that are always selected):

    | Change | fingerprint | statistical | smoke, sanitizer | unit | module | protocol | chart | feature, validation |
    | --- | --- | --- | --- | --- | --- | --- | --- | --- |
    | string literal in `Ipv4.cc` | 105 | 41 | 43 | 0 | 5 | 368 | 0 | all |
    | new member in `Ipv4.h` | 3003 | 730 | 731 | 8 | 675 | 1005 | 10 | all |
    | a comment in line 1 of `Ipv4.cc` | 3 | 10 | 14 | 0 | 296 | 1005 | 0 | none |
    | INET 0af9da9b1e (`#expected-result` comments) | 23 | 18 | 22 | 0 | 2 | 351 | 0 | all |

    The comment moves all lines of `Ipv4.cc`, so R3 selects the opp tests that ran a function of
    the file (296 module, 654 protocol tests). A refinement for phase 6: a line number reaches a
    text output only with the name of the file, so R3 needs to select only the opp tests whose
    `.test` file names the changed file.
- [x] Feature tests (v1 rule). Their smoke runs use the store of D2c.
  - opp_repl 01a7d84: a kind without records (`KIND_LEVEL_KINDS`). A C++, msg, NED, ini or build
    file, or a file that a run used, selects all feature tests if a rule of the file other than R3
    applies; the key is `feature:<type>:<feature>`. Checked: of the 253 INET feature tests, the
    string literal selects all and a comment none.
- [x] For each kind, decide where its records come from: from its push job in coverage mode
  (D11), or from the weekly map. With the weekly map, the A..B side of the kind is wider.
  - Decided by the user on 2026-11-26 (D12).
  - Facts: the push jobs of the unit, module, queueing, protocol and packet tests run in debug mode,
    which is about as fast as coverage mode, as the fingerprint debug jobs (D11). The statistical
    and chart jobs run in release mode, and coverage mode is 3 and 5 times slower for them (phase
    0). The smoke and sanitizer tests have no push job. Recommendation: the opp kinds and packet
    from their push jobs, as the fingerprint tests; statistical, smoke, sanitizer and chart from
    the weekly map.

### Phase 4 — validation

- [ ] Replay (V1) over the last 200 INET master commits, for each kind in the map, first the
  fingerprint tests. Repair each rule that misses a test. A kind goes into the CI of phase 5 only
  after its replay finds no missed test.
  - The ground truth of the 200 first-parent commits up to 28f1dc534c (2026-11-13 to 2026-11-25):
    29 commits change 854 fingerprint values of the store (1 of them only the store), 27 move the
    `statistics` pin, 8 the `media` pin.
  - The method: 14 fingerprint maps at 28f1dc534c~p for p in 5, 14, 46, 56, 64, 99, 107, 112,
    115, 123, 127, 135, 142 and 193, so that each commit with ground truth has a map at most 6
    commits older than its parent (`p4/maps.sh`, a scratch worktree with a coverage build, a copy
    of opp_repl at bcc8437). For each commit, the selection of `--changes <commit>` with that map
    must select each test whose stored fingerprint changed by a rule other than E1, the store rule
    itself; a test that is not in the map is selected anyway. The selection is correct with any
    map (diff(A,B) ∪ diff(A,C)), so a test that it misses is a defect of a rule or an assumption.
  - The fingerprint result (2026-11-26, opp_repl 2f36b13, the 14 maps built in 2:36): of the 854
    changed values of 29 commits, a rule other than E1 selects 848. The other 6 are of two commits
    that change no code: bee6f62eea records the mipv6 Handover fingerprints again (only the
    store), and b436a63418 records the baselines again for the Ubuntu 26.04 runners (the store and
    the pins). So the replay finds no defect of a rule. 13 of the 29 commits select all tests, so
    their check proves less; at the age 0, the own change selects all tests through R4 for a
    header that most translation units include (`Ipv6InterfaceData.h`, `BlockAckRecord.h`).
  - The ratio of the fingerprint tests by the age of the map (the commits between the map and the
    parent of the commit), over the 193 commits with a map:

    | Age | Commits | Median of the selected tests | All tests | Below 5% |
    | --- | --- | --- | --- | --- |
    | 0 | 14 | 1.9% | 21% | 64% |
    | 1 to 2 | 28 | 2.5% | 36% | 57% |
    | 3 to 6 | 45 | 100% | 51% | 40% |
    | 7 to 15 | 36 | 100% | 67% | 25% |

    A map at the parent (D11) selects a median of 1.9% of the tests; from 3 commits of age on, more
    than half of the commits select all tests. A selection needs a median of 0.7 s, at most 7.2 s.
  - The statistical result (12 statistical maps at the positions that serve the pin moves, about
    9 minutes each): 27 commits move the `statistics` pin, and 214 `.sca` files change between the
    pins. A rule other than E2, the pin rule itself, selects 202 of their tests; the other 12 are
    of b436a63418, the new baselines for the Ubuntu 26.04 runners, which changes no code. Two pin
    moves (bdbb4baae1, bc39ec7571) name a commit that the `statistics` checkout does not have, so
    E2 selects all statistical tests there.
  - The replay uses a map whose commit is near the replayed commits. diff(A,B) grows with the
    distance, and a big diff gives a correct but wide selection, which makes the ratio useless.
- [x] The mutation sample (V3), once for the fingerprint tests.
  - The method (`p4/v3/v3.py`): in the scratch tree at INET 0af9da9b1e with a release build and the
    fingerprint map of the same commit, 12 mutations, one in each of 12 folders below `src/inet`: an
    integer literal in an arithmetic or a comparison of a function that ran in 5 to 600 runs gets
    1 more. After each build, all 4726 fingerprint tests run; each test whose result differs from
    the run without a change must be in the selection of the change (`--changes worktree`).
  - Result (2026-11-26, opp_repl 2f36b13): all 12 mutations build, and the selection misses no
    test. 7 mutations change the results of 3621 tests; the selection is tight for most of them
    (3 of the selected tests are the run that did not end normally):

    | Function of the mutation | Runs | Changed | Selected |
    | --- | --- | --- | --- |
    | `Material::getDielectricLossTangent` | 11 | 18 | 36 |
    | `AckingMac::encapsulate` | 209 | 21 | 630 |
    | `Arp::processArpPacket` | 326 | 944 | 947 |
    | `WireJunction::initialize` | 395 | 523 | 526 |
    | `PacketClassifierBase::checkPacketStreaming` | 166 | 498 | 501 |
    | `Aodv::processPacket` | 31 | 93 | 96 |
    | `TransportPseudoHeaderSerializer::serialize` | 528 | 1524 | 1587 |

    The other 5 (in `DhcpClient`, `DriftingOscillatorBase`, `BitVector`,
    `LineSegmentsMobilityBase`, `InterpacketGapInserter`) change no result. The run without a
    change needs 2:36 for the 4726 tests; a mutation needs about 2:30 with its build.
- [ ] Write the selection ratio for each suite into this plan.

### Phase 5 — CI and the agent documentation

The design is in section 15.

- [ ] The weekly coverage workflow writes the per-run profiles and the map. The report job commits
  `map/` to the `master` branch of `inet-framework/coverage` (8.4).
- [ ] The map header gives the commit of opp_repl also for an installed package, so that a pull
  request job can install the same opp_repl (15.2). The jobs install opp_repl with `pip`, which
  leaves no git checkout; `opp_repl/_version.py` has `commit_id`.
- [ ] The viewer page on `gh-pages`, and links to it from the `genhtml` pages.
- [ ] The shadow check (V2) in the weekly workflow.
- [ ] opp_repl finds and reads the map from the history of `inet-framework/coverage`.
  `opp_checkout_test_baselines` also checks out this repository, next to `statistics` and
  `media`, so that `opp_select_tests` finds the map without `--map`. If `gh` is available, it also
  downloads the map of the newest finished push run (D11).
- [ ] Rule H6: a change of a CI file selects all tests (5.6).
- [ ] Calibrate the store of simulation-time limits of D2c on the CI runner, in the mode of the
  smoke tests (a manual workflow job), and replace the local values of INET 038e4a5a20.
- [ ] R6 v2 (D10, 5.1), before the pull request jobs.
- [ ] The push run of the fingerprint tests runs in coverage mode instead of debug mode and saves
  its map as an artifact (D11, 8.4). Each split saves its records, and one more job writes the map
  from them and from the tables of the build. First compare the compile flags of `MODE=debug` and
  `MODE=coverage`: the coverage build must have all flags and defines of the debug build.
- [ ] D5: the report gives the cost of the age of the map, and a map that is older than 2 days
  gives a warning (section 9, step 6).
- [ ] The pull request job of 15.2 for each kind that passed its replay, first the fingerprint
  tests. It selects before the build (INET T8).
- [ ] The tests of each kind at C without a build, for the selection before the build (T8): the
  `.test` files of the opp tests, the folder of the packet test; the kinds of simulations need
  their configs at C.
- [ ] The check of each push (V4, 15.3).
- [ ] The agent documentation of 15.4: INET `run-the-gates.md` and `testing.md`, opp_repl
  `doc/test_map.md`.
- [ ] opp_ci: a selection option for branch runs.
- [ ] Later: TR-CI-EVERY-COMMIT, with the selection of each commit of a pull request (15.3).

### Phase 6 — refinements, only where the replay shows a cost

- [ ] R10 v2: generate the `_m` files at both sides.
- [ ] A narrow rule for registrations (R7). R6 v2 moved to phase 5 (D10).
- [ ] I2 v2: section logic for included ini files.
- [ ] H5: instrument omnetpp.
- [ ] Refresh the map for each test that a selected run executes in coverage mode.
- [ ] R4: the constructors and destructors of the generated class descriptors depend only on the
  name of their class and of its base class, which their own `.msg` file declares. If R4 leaves
  them out, 361 instead of 620 INET headers select all runs (phase 2). This is an assumption
  about the generated code, so it needs a decision.
- [ ] R3 for the opp tests: select only the tests whose `.test` file names the changed file (a
  line number reaches a text output only with the name of the file). Phase 3 measured 296
  module and 654 protocol tests for a comment in line 1 of `Ipv4.cc`.
- [ ] H4 v2: the build tables also read the objects of the support libraries of the opp tests,
  so that a change in a support library selects only the tests that ran the changed code.
- [ ] E3 v2: a moved `media` pin selects only the chart of each changed image, not all charts of
  its folder.
- [ ] R2: the column of the braces, so that a change on the line of a one-line function body
  (`int get() const { return x; }`) is inside the body.

## 13. Decisions

- **D1 (decided 2026-11-25)** The map run uses the coverage build that opp_repl has now
  (`-m coverage`), and it is the weekly coverage run. The map goes into the `inet-framework/coverage`
  repository, so that people can browse it (8.4).
- **D2 (decided 2026-11-26)** The CPU-time limits (section 7): D2c, a fixed `sim-time-limit` for
  each config in a store of its own. The user chose it over D2b, because D2b has no record of the
  code at the stop point, and over D2a, because D2c needs no omnetpp change.
- **D3 (decided 2026-11-26)** The NED closure stays in opp_repl for now. The omnetpp change O1 comes
  only when the failed lookups cost too much (4.3).
- **D4 (decided by the phase 0 measurement)** File trace: `LD_PRELOAD` (about 1% against 33% for
  `strace`, the same project files).
- **D5 (decided 2026-11-26)** No age limit for the map. Each report gives the cost of the age, and
  a map that is older than 2 days gives a warning (section 9, step 6). The measurement (15.1)
  showed that the age, not a warning, decides the benefit, so D10 and D11 came from this decision.
- **D6 (decided 2026-11-25)** The weekly run gets the suites that the map needs and that it does
  not run now: statistical, smoke, chart, validation and speed (8.1). The user moved this step into
  phase 0. Speed cannot run now (section 6).
- **D7 (decided 2026-11-25)** The `master` branch of `inet-framework/coverage` can lose old history
  (8.4).
- **D8 (decided 2026-11-26)** The fingerprint tests go through all the steps first: the replay
  (phase 4), the map and the jobs of phase 5, and the agent documentation. Then phase 3 adds one
  kind at a time on the same path. Changed by the user on the same day: phase 3 comes now, before
  phases 4 and 5. Each kind of phase 3 still goes through the replay of phase 4 before CI uses it.
- **D9 (decided 2026-11-26)** A pull request job uses the omnetpp commit and the opp_repl commit of
  the map, not the newest commits of `omnetpp-6.x` and `github_ci`. Without this, H1 or H5 would
  select all tests on 49 of 84 days (15.1). The other option was not chosen: pins of omnetpp and
  opp_repl in `inet.opp`, as for the baselines.
- **D10 (decided 2026-11-26)** R6 v2 (5.1) comes before the pull request jobs of phase 5, not in
  phase 6. Without it, a hunk that only renames or removes functions selects all tests (15.1).
- **D11 (decided 2026-11-26)** Each push to `master` makes a map of the fingerprint tests: its debug
  fingerprint jobs become coverage jobs (about 7% slower), and the map is an artifact of the run
  (8.4). A pull request job uses the map of the newest finished push run, so the map is minutes or
  hours old, and the environment of D9 is that of the last push run.
- **D12 (decided 2026-11-26)** The records of the unit, module, queueing, protocol and packet tests
  come from their push jobs in coverage mode, as for the fingerprint tests (D11): these jobs run in
  debug mode, which is about as fast. The records of the statistical, smoke, sanitizer and chart
  tests come from the weekly map: their jobs run in release mode or not on a push, and coverage
  mode is 3 to 5 times slower than release.

No decision is open.

## 14. Risks

- The per-run profiles can be too slow or too large for the runners. Phase 0 measures this.
- More suites make the weekly run longer. The jobs have a timeout of 150 minutes, and the chart job
  has 240 minutes, because its simulations cannot be split now. If the chart job gets near the
  limit, the split of the chart tests must also divide their simulations (an opp_repl change).
- The map can make the `inet-framework/coverage` repository grow fast. The job drops old history
  (D7). A force push to `master` needs a deploy key that is allowed to do it.
- Wide headers (`Packet.h`, `INETDefs.h`) select almost all tests. This is correct, but such a
  change gets no benefit.
- R7 is wide, and a new module selects all tests. The replay shows if a refinement is worth the
  work. R6 v2 (D10) narrows R6.
- The rules in 4.4 and section 7 are assumptions. V1 and V2 find a defect when an assumption is
  false in practice.
- A pull request job tests in the environment of the map (D9). With the maps of the push runs
  (D11), this is the environment of the last push run, some hours old. A change of omnetpp or
  opp_repl that breaks INET shows first in the push run, not in the pull requests.
- If the fingerprint store of `master` changes for a newer omnetpp, E1 selects the changed tests in
  each pull request, and they fail with the omnetpp of the map until a push run makes a new map.
- The values of the store of D2c age. If a model gets slower, its smoke run takes more than 1 s.
  The safety stop limits the cost, and a new calibration run corrects the values.
- A base B that is older than the retention time of the artifacts gets the weekly map, so its
  selection is wider.

## 15. CI and the agent documentation

The user agreed to this design on 2026-11-26 (D8 to D11). Phase 5 has its steps.

### 15.1 Facts (2026-11-26)

- The test workflows of INET now:

  | Event | Workflows |
  | --- | --- |
  | Pull request and push to `master` | fingerprint (debug and release, 4 splits each), statistical, chart; build-linux for `src/**` |
  | Push to `master` only | unit, module, queueing, protocol, packet, validation |
  | Weekly | coverage (Sunday, the map run); feature, the macOS and the Windows builds (Saturday) |

- The test jobs check out the newest commit of `omnetpp-6.x` and install the newest commit of the
  opp_repl branch `github_ci`. From 2026-08-30 to 2026-11-22 (84 days), omnetpp changed a file
  outside the harmless files of H5 on 20 days, and opp_repl on 15 days. With a map each Sunday, H1
  or H5 would select all tests on 49 of the 84 days: on 40 days because of omnetpp, on 31 days
  because of opp_repl.
- `ProjectInfo.classify` gives the class "data" to `.github/workflows/*.yml` and
  `_scripts/github/*.sh`. No map record names these files, so a change of them selects no test.
- TR-CI-EVERY-COMMIT of INET has no enforcement: the workflows test only the head of a pull
  request.
- INET `AGENTS.md` only points to other documents, and DR-NO-SECOND-COPY does not let it copy a
  rule. For tests, it sends agents to `doc/project/guide/run-the-gates.md` and
  `doc/project/rule/testing.md`.
- The age of the map (measured for D5): the A..B side alone, with A = the map commit 0af9da9b1e and
  B = k commits older, selects 3 of 4726 tests (the abnormal run) for k = 1 to 12 (4 to 21 changed
  files), and all tests for k = 20 (37 files; R6 in `Mldv1.cc`), 30 and 45. INET `master` got 522
  commits in the 30 days before 2026-11-25, about 120 each week, so a weekly map often selects all
  tests.
- On GitHub, fingerprint split 0 needs 22.6 minutes in debug mode and 24.3 minutes in coverage mode
  (phase 0), so a coverage job costs about 7% more than a debug job.
- The smoke, sanitizer and feature tests stop after 1 s of CPU time; INET has 672 smoke tests.
  omnetpp has `sim-time-limit`, `cpu-time-limit` and `real-time-limit`, and no event-count limit.
  No workflow on `master` runs the smoke or sanitizer tests; the feature tests run weekly.

### 15.2 The job of a pull request

The selection only decides how long a pull request waits. `master` keeps the full run (15.3). Each
kind gets this job after its replay (phase 4). Until then, the kind runs as now.

1. Check out INET with the history back to the map commit (`fetch-depth: 0`). Download the map of
   the newest finished push run whose commit is an ancestor of B (D11). Without one, use the weekly
   map from `inet-framework/coverage`.
2. Read the header of the map. Check out omnetpp at its `omnetpp_commit`, and install opp_repl at
   its commit (D9). The pull request thus tests only its own change, in the environment of the map.
3. Select before the build (INET rule T8, decided 2026-11-26 in INET
   `plan/pending/master-guards.md`): `opp_select_tests --kind <kind> --summary`. With
   `Selected 0 of M`, the job skips the build and the tests, and it is green after a few minutes;
   else it builds as now. A selection before the build must know the tests of the kind at C,
   also the new ones, because a test that the map does not know is always selected: the
   fingerprint tests come from the store at C, the opp tests from their `.test` files at C (not
   written yet). A kind whose tests at C the selection cannot list without a build keeps the list
   of paths that the INET jobs use now, until it can.
4. Run `opp_run_<kind>_tests ... --changes HEAD`. GitHub tests the merge commit of the pull
   request, so B is the newest commit of `master` and C is the merge commit.
5. With the label `full-tests`, run all tests of the kind, without `--changes`. A change of a CI
   file (H6) and the reasons of 4.3 select all tests with no help from the workflow.

The job always runs and reports `Selected N of M`, also for N = 0, so each required check gets a
result (INET W1: no path filter in the trigger of a required job). The names of the pull request
jobs stay the same: `fingerprint-tests (debug, N)` and `fingerprint-tests (release, N)` are
required (INET R6), also when the push jobs run in coverage mode (D11); a change of the name or
the matrix of a required job lands together with the change of the ruleset (INET W2). After phase 3, the kinds that run only on a push now (unit, module, queueing, protocol,
packet, validation) also get this job.

### 15.3 Push to `master`, the week, and each commit

- A push to `master` runs all tests, as now, with the newest omnetpp and opp_repl. Its fingerprint
  jobs run in coverage mode instead of debug mode, and the run saves the map of its commit (D11,
  8.4). Nobody waits for this run, and it is the input of the check V4 (section 10).
- The weekly coverage run makes the new map and does the check V2.
- Later: each commit of a pull request runs the tests that its own change selects (`--changes
  <commit>`). This enforces TR-CI-EVERY-COMMIT at the cost of one build for each commit.

A test that the selection of a pull request misses can fail only after the merge. The push run then
finds the failure, and V4 names the rule. This is not less protection than now: now the pull
requests do not run the unit, module and protocol tests at all.

### 15.4 The agent documentation

The changes go into the documents that `AGENTS.md` points to, not into `AGENTS.md`. The INET
changes go on a local INET branch.

- INET `doc/project/guide/run-the-gates.md`:
  - "During focused development": first `opp_select_tests --changes origin/master...worktree
    --explain`. It lists the tests that the change can affect, with the rule and the changed place
    for each test. `opp_show_test_map` tells which tests use a file or a function. The agent picks
    the directly related cases from this list. TR-FOCUSED-EVIDENCE does not change.
  - "Before every push": a new step, `opp_run_all_tests --changes origin/master...HEAD`. The
    report gives the line `Selected N of M`, the map commit and each reason for all tests.
  - The local omnetpp, opp_repl or compiler is usually different from the map, and then the
    selection gives all tests. The agent then adds `--ignore-environment` and says so in the
    report. CI never uses this option.
- INET `doc/project/rule/testing.md`: a new rule, for example TR-SELECTED-PASS: "Before a push, the
  tests that the selection gives for the series pass." The selected tests show that the change
  breaks no other test. They do not prove the change itself, which still needs its directly related
  cases. The pull request jobs enforce the rule (T3).
- opp_repl `doc/test_map.md`: the sections "In development" and "In CI".
