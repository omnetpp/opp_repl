# Test map

The test map tells, for each test, which C++ functions, NED types, ini sections
and other files its runs used at one commit of the project (the map commit).
The change-based test selection (`opp_select_tests`, and the `--changes` option
of the test commands) reads the map and a diff, and selects only the tests whose
outcome the change can change. Now the map holds the fingerprint, statistical,
smoke, sanitizer, unit, module, queueing, protocol, packet and chart tests, and
the selection selects the feature and validation tests all together or not at
all; the speed tests all run.

The map comes from a run of the tests with the coverage build (see the
[Coverage](coverage.md) guide). The same runs also give the coverage report.

## Make a map

Build OMNeT++ and the project in coverage mode, then run:

```bash
opp_update_test_map -p inet --no-build
```

The command does three steps:

1. It runs the fingerprint tests of the project in coverage mode, and each
   run writes its record into `coverage/test-map/records` in the project
   root. The command removes the old records of that folder first.
   `--kind statistical` runs the statistical tests instead; give `--kind` more
   than one time for more kinds, for example `--kind fingerprint --kind
   statistical --kind smoke`. The records of the smoke tests also serve the
   sanitizer tests. The kinds are `fingerprint`, `statistical`, `smoke`,
   `unit`, `module`, `queueing`, `protocol`, `packet` and `chart`.
2. It makes the build tables from the coverage build, and writes them to
   `build-tables.json.gz` in the records folder.
3. It writes the map into `coverage/test-map/map` in the project root.

`update_test_map(simulation_project=..., ...)` does the same in Python. The
filter options of the run commands also apply, for example
`-w examples/ethernet`; the map then holds only these tests.

Make the map from a tree without changes: the header of the map records the
commit, and a map of a tree with changes does not describe that commit.

Options:

- `--records FOLDER` — a records folder. Give it more than one time to merge
  the records of several runs, for example of several CI jobs. The run writes
  into the first folder.
- `-o FOLDER` — the folder of the map. The command replaces an old map in it,
  but it does not remove a folder that holds something other than a map.
- `--no-run` — do not run the tests; write the map from the records that the
  folders hold.
- `--build-tables FILE` — read the build tables from a file instead of the
  coverage build. Without this option, the build tables need a profile in the
  profile pool, also with `--no-run`.

### Records in several jobs

A CI workflow can divide the tests over several jobs. Each job runs its part
with records, and one job then writes the map. The run commands of the other
kinds of the map take `--test-map-records` too.

```bash
# in each job
opp_run_fingerprint_tests -p inet -m coverage --split-count 4 --split-index 0 --test-map-records records-0
# in one job with the coverage build and the records of all jobs
opp_update_test_map -p inet --no-run --records records-0 --records records-1 --records records-2 --records records-3
```

## Records

A run with `--test-map-records FOLDER` writes the folder `FOLDER/<run id>/`.
The run id is the first 10 hex digits of the SHA-1 of the run key, for example
`fingerprint:examples/adhoc/hostautoconf/omnetpp.ini:General:#0:100s`. The key
starts with the kind of the test, so a statistical test of the same config has
another run. The tests of one fingerprint group share one run, so the key has no
ingredients. The key of a statistical or smoke test is the key of its run. A
sanitizer test stops where the smoke test of its config stops, and the sanitizer
only examines the code that runs, so the run of the smoke test is also its run:
its key is the key of that run with the kind `sanitizer`.

An opp test (unit, module, queueing, protocol) runs `opp_test run` with the
test program that opp_test made from its `.test` file. The record holds the
profile and the file trace of all processes of the run, and `includes`: the
project files that the own code of the test includes, from the `.d` files of the
test program. Its key is the kind and the path of the `.test` file, for example
`unit:tests/unit/Checksum_1.test`. The packet test is one program of its own,
with the key `packet:tests/packet`. A `%testprog` test can start another
program, so its record has no NED types, and it does not count as a normal end.

A chart test draws a chart of an `.anf` file from the results of the
simulations of the folder of the file. Its simulations write the records, with
the kind `chart`, and the run writes `chart-tests.json` into the records folder:
the run keys of the simulations of each chart test. The key of a chart test is
`chart:<.anf file>:<chart id>`. The chart code runs in the opp_repl process,
which the file trace does not see; rules H2 and H3 cover it.

A smoke test that stops after a CPU-time limit stops at a different event on
each machine, so its record does not show what a test run uses. With the store
of simulation-time limits of the project (see [Smoke Tests](smoke_tests.md#the-end-of-a-run)),
the smoke tests and their records stop at the same event. A run that a CPU-time
or a real-time limit stopped does not count as a normal end.
Records need the coverage build (`-m coverage`).

- Each run writes its own profile. After the run, opp_repl merges it into
  `<run id>.profdata` in the profile pool, and writes the functions that ran
  into `functions.txt.gz`. The coverage export of the pool gives the same lcov
  file as without the records.
- An `LD_PRELOAD` library traces the files that the run opens, examines and
  lists, and the lookups that fail (`opp_repl/test/test_map/filetrace.c`;
  opp_repl compiles it with `cc` into the records folder). `files.txt` holds
  the project files that the run used: `read`, `examined`, `listed` and
  `lookup`. It does not hold the outputs of the run, the result folder, the
  build folder `out`, or the NED folder walk of omnetpp.
- `run.json` holds the key, the exit code and the end of the run (its last
  event number and simulation time), the NED types that the run instantiated
  (`--print-instantiated-ned-types`), and the section chain of its config
  (`-q sectioninheritance`). opp_repl writes it last, so a record without it
  is not complete.

## Build tables

The build tables come from the coverage build of the map commit:

- the function table: for each function of the C++ sources, its name, file and
  the line range of its body (`llvm-cov export`);
- the emitter table: for each function, the translation units whose object
  file holds its code, from the profile counters (`__profc_<name>`) in the
  `nm` output of the objects;
- the include table: for each translation unit, the project headers that it
  includes (the `.d` files of the build);
- the NED type table: for each NED type of the NED folders, its file and the
  types that it refers to by `extends` and `like`, resolved with the name rules
  of omnetpp (`opp_nedtool` gives the syntax tree).

For INET, the tables take about 10 s and 1.8 GB of memory.

## Layout of the map

The map is a tree of text files with the same paths as the project. Each map
file tells which runs used which part of the source file of the same name:

| Map file | Content |
| --- | --- |
| `src/.../Ipv4.cc.json` | `functions`: for each function body, its line range, its name, the runs that ran it and the translation units that emit it (more than 20 as the id of a set); `tu_runs`: the runs that ran a function that the translation unit emits |
| `src/.../Ipv4.h.json` | the functions of the header, and `included_by`: the translation units that include it |
| `<path>.json` of a file that the own code of a test includes | `test_runs`: the runs of the opp tests and binary tests whose code includes it |
| `src/.../Ipv4.ned.json` | `types`: for each declared type, the runs that used it (the instantiated types and the types that they refer to) |
| `examples/.../omnetpp.ini.json` | `sections`: for each section, the runs whose section chain has it |
| `<path>.json` of another file | `data`: the runs that read or examined the file (only files that git tracks), or that looked it up and did not find it |
| `<folder>/index.json` | the number of runs that used something below the folder, for each kind; `listed`: the runs that listed the folder |
| `runs.json` | for each run: its key, exit code, end, section chain, and `normal_end` |
| `tests.json` | for each test kind and test key: its runs |
| `emitter-sets.json` | the sets of more than 20 translation units that emit a function, by id |
| `release-only.json` | the blocks that only a release build compiles, with their names, the project files that they include, and their runs (see below) |
| `header.json` | the project, the map commit, the omnetpp commit, the opp_repl version and commit (also of an installed package, from `opp_repl/_version.py`), the compiler, the enabled features, the versions of the Python packages of the charts, the date |

A set of runs is `"all"`, `{"except": [run ids]}` if it holds more than half
of the runs, or a list of run ids. Each map file has one JSON value on each
line, so that a git diff of two maps shows one function or one key on each
line. This is version 3 of the map; version 2 had no `release-only.json`, and
version 1 had only the number of more than 20 translation units.

The release-only blocks are the branches of the preprocessor conditionals that
a release build compiles and a debug or coverage build does not, for example
the branch of `#ifdef NDEBUG`. The writer evaluates each conditional in both
configurations, also through the macros whose definition depends on `NDEBUG`.
The runs of a block are the runs of the function that holds it, or of the
translation units that include its file.

## Query a map

```bash
# the tests that ran the function at line 70 of Ipv4.cc
opp_show_test_map -p inet src/inet/networklayer/ipv4/Ipv4.cc --line 70
# the parts of a file and the number of runs of each part, and the tests that used it
opp_show_test_map -p inet src/inet/networklayer/ipv4/Ipv4.ned --tests
# the number of runs that used something below a folder
opp_show_test_map -p inet src/inet/networklayer
# the files that the runs of a config used
opp_show_test_map -p inet --test 'examples/ethernet/lans/omnetpp.ini:MixedLAN:'
```

`--map FOLDER` reads another map. `show_test_map()` does the same in Python.

## Select tests

`opp_select_tests` prints, for each kind of test, the tests whose outcome a
change can change:

```bash
# the working tree and its untracked files against HEAD (the default)
opp_select_tests -p inet
# a commit, a range, a branch since its merge base, or a patch file
opp_select_tests -p inet --changes HEAD
opp_select_tests -p inet --changes master..topic
opp_select_tests -p inet --changes master...worktree
opp_select_tests -p inet --changes fix.patch
# also the rules of each changed file and the reasons for each test
opp_select_tests -p inet --explain
```

The commands that run tests take the same option, and run only the selected
tests. A kind of test that the map does not hold runs all its tests.

```bash
opp_run_fingerprint_tests -p inet --changes master...worktree
```

Options:

- `--changes CHANGE` — `worktree`, a commit (against its first parent),
  `rev1..rev2`, `rev1...rev2` (from the merge base of the two), or the path of a
  patch file (applied to `HEAD` in a temporary index, so the working tree does
  not change). `rev2` can be `worktree`.
- `--map FOLDER` (`--test-map FOLDER` for the commands that run tests) — the
  folder of the map.
- `--kind KIND` — only this kind of test; give it more than one time for more
  kinds.
- `--summary` — only the numbers; `--json` — the selection as JSON.
- `--ignore-environment` — see the list of the tests that are always selected.

`select_tests(simulation_project=..., changes=...)` does the same in Python.

### Which map

Without `--map`, the selection takes the best of these maps: the local map
`coverage/test-map/map`, and each version of the map in the history of the map
repository of the project. A map repository holds a map in its folder `map/`,
for example the weekly map of the coverage workflow. The project names it in its
`.opp` file:

```python
test_parameters={
    "coverage": {"baseline": {"repository": "inet-framework/coverage", "branch": "master", "folder": "coverage-map"}},
}
```

`opp_checkout_test_baselines` clones it and gets the head of the branch. Of the
maps whose commit is an ancestor of the base B, the map with the fewest commits
to B wins, because an older map selects more tests. `--map` also takes the
checkout of a map repository. The report gives the age of the map in commits,
and the number of tests that only the age selects; a map that is older than 2
days gives a warning.

### In development

Before a push, run the tests that the change of the branch can change:

```bash
opp_select_tests -p inet --changes origin/master...worktree --explain
opp_run_all_tests -p inet --changes origin/master...HEAD
```

The environment of a developer is usually not the environment of the map: other
commits of omnetpp and opp_repl, or another compiler. Then the selection selects
all tests; `--ignore-environment` gives a warning instead. The selection then
assumes that the environment does not change which code the tests run.

### In CI

A pull request job selects its tests before it builds (INET rule T8):

1. Get the map of the newest finished push run whose commit is an ancestor of
   the merge base, else the weekly map.
2. Install the commits of omnetpp and opp_repl that the header of the map
   names (`omnetpp_commit`, `opp_repl_commit`).
3. Run `opp_select_tests --kind <kind> --summary`. With `Selected 0 of M`, skip
   the build and the tests; else build, and run the test command with
   `--changes HEAD` (the merge commit of the pull request).

The selection before the build needs the tests of the kind at the merge commit,
also the new ones: the fingerprint tests come from the store, the opp tests from
their `.test` files, and the packet test from its folder. A kind of simulations
whose configs need the build (statistical, smoke, chart) cannot skip its build
this way yet.

### How the selection works

The map describes the map commit A. A change goes from the base B to the target
C. The selection reads diff(A,B) and diff(A,C), and selects each test whose
inputs one of the two diffs changes. If neither diff changes what a test used,
the test has the same outcome at B and at C. So an old map gives a wider
selection, but not a wrong one.

| Changed file | Selected tests |
| --- | --- |
| C++ file, only comments or white space | none |
| C++ file, inside a function body | the tests that ran the function |
| C++ source, outside the function bodies; a new or removed source | all tests, because the static initialization of each process can change |
| C++ header, outside the function bodies; a removed header | the tests that ran a function whose emitting translation units all include a changed header, and the tests whose own code includes it |
| a file outside the C++ folders that the own code of a test includes | the tests whose own code includes it |
| `.test` file | its opp test |
| `.anf` file | its chart tests |
| file of a Python folder of the project (INET `python/`) | all chart and validation tests |
| `.opp` file, only the pin of the chart baseline moved | the chart tests of each folder with a changed image in the `media` checkout; all chart tests if the checkout does not have both commits |
| file of the support library of a kind (`lib_folder`, else `<test_folder>/lib`) or of the folder of a binary test | all tests of that kind |
| C++ file, the body of a `constexpr` function or of a function with a deduced return type | as outside the function bodies |
| `.msg` file | as its generated `_m.h` header; a new or removed `.msg` file selects all tests |
| NED file | the tests that used a type of the file; for a new type, also the tests that used a type with the same simple name; for `package.ned`, all types of the package |
| NED file that omnetpp cannot load: a syntax error, a type that another file declares too, a package that does not agree with the folder | all tests |
| ini file | the tests whose section chain has a changed section, also for a change of a key that opp_repl reads from a comment (`#expected-result`, `#abstract`, `#emulation`, `#bounded`); for a change of iteration variables, `repeat` or `constraint`, all tests of the ini file; the tests whose ini file includes the file |
| fingerprint store | the tests whose entry changed, without the timestamp |
| `.opp` file, only the pin of the statistical baseline moved | the tests whose `.sca` file differs between the two pins in the `statistics` checkout; all statistical tests if the checkout does not have both commits |
| `.opp` file | for other changed test parameters of a kind, all tests of that kind; for other changed fields, all tests |
| build file: `Makefile` and `makefrag` in the root or in a C++ folder, `.oppbuildspec`, `.oppfeatures`, `.oppfeaturestate`, `.nedfolders`, `.nedexclusions` | all tests |
| file of the CI jobs: `.github/workflows/`, and the paths of `ci_files` of the project | all tests |
| other file | the tests that read, examined or looked up the file; for a new or removed file, also the tests that listed its folder |

The feature and validation tests have no records. A change of a C++, msg, NED,
ini or build file, or of a file that a run of the map used, selects all of them,
if a rule of the file other than the line shift applies. Other changes, for
example of comments, select none. A validation run with `--changes` runs all
validation tests or none.

Some tests run in release mode, which compiles code that the coverage build of
the map does not. A changed function whose name is in a release-only block, or
a changed file that such a block includes, also selects the runs of the block.

A C++ change that moves lines changes `__LINE__` below it. `__LINE__` goes only
into log lines, error messages and the names of static objects. So a moved line
selects only the tests that compare a text output, the opp tests.

These tests are always selected:

- a test that is not in the map, for example a new config or a new run number;
- a test whose run in the map did not end normally, also a run that a CPU-time
  limit stopped;
- a test that matches a regular expression in the list
  `test_parameters[kind]["test_selection"]["always"]` of the `.opp` file;
- all tests, if the environment differs from the map: the map comes from a tree
  with changes, the opp_repl or omnetpp commit differs in a file other than
  documentation, or the compiler or the enabled features differ;
- all chart tests, if the versions of matplotlib, numpy, pandas or scipy differ
  from the map: another version can draw another image.
  `--ignore-environment` gives a warning instead.

## Limits

- The speed tests write no records yet, so they all run.
- A moved `media` pin selects all chart tests of a folder with a changed image,
  not only the chart of that image.
- The support library of the opp tests selects all tests of its kind (rule H4,
  v1): its code is not in the build tables.
- The check whether a config is interactive also starts the simulation, so an
  interactive config, which the test skips, has a record that did not end
  normally. The selection always selects it, and the run skips it.
- The selection is correct if the assumptions of section 4.4 of the plan
  (`plan/pending/test-selection.md`) are true: the tests are deterministic, the
  build mode does not change the path of the code (no undefined behavior), and
  each inline and template function has the same definition in all translation
  units.
- Some rules are wide. Each process runs the constructors of the generated
  class descriptors, so a change of a header that a `_m.cc` file includes
  selects all tests.
- A run that does not end normally (an exit code other than 0, no profile, or
  no section chain) has `normal_end` false in `runs.json`. Such a run can have
  used inputs that the map does not show, for example NED lookups that failed.
- The file trace sees the calls of the C library that it replaces. A program
  that makes system calls directly is not traced.
- The NED type table does not see the NED lookups that failed in a run.
