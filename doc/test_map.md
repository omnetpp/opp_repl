# Test map

The test map tells, for each test, which C++ functions, NED types, ini sections
and other files its runs used at one commit of the project (the map commit).
The change-based test selection of opp_repl will read the map and a diff, and
select only the tests that a change can affect. The selection is not written
yet. Now the map holds the fingerprint tests.

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
2. It makes the build tables from the coverage build, and writes them to
   `build-tables.json.gz` in the records folder.
3. It writes the map into `coverage/test-map/map` in the project root.

`update_test_map(simulation_project=..., ...)` does the same in Python. The
filter options of `opp_run_fingerprint_tests` also apply, for example
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
with records, and one job then writes the map:

```bash
# in each job
opp_run_fingerprint_tests -p inet -m coverage --split-count 4 --split-index 0 --test-map-records records-0
# in one job with the coverage build and the records of all jobs
opp_update_test_map -p inet --no-run --records records-0 --records records-1 --records records-2 --records records-3
```

## Records

A run with `--test-map-records FOLDER` writes the folder `FOLDER/<run id>/`.
The run id is the first 10 hex digits of the SHA-1 of the run key, for example
`fingerprint:examples/adhoc/hostautoconf/omnetpp.ini:General:#0:100s`. The
tests of one fingerprint group share one run, so the key has no ingredients.
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
| `src/.../Ipv4.cc.json` | `functions`: for each function body, its line range, its name, the runs that ran it and the translation units that emit it; `tu_runs`: the runs that ran a function that the translation unit emits |
| `src/.../Ipv4.h.json` | the functions of the header, and `included_by`: the translation units that include it |
| `src/.../Ipv4.ned.json` | `types`: for each declared type, the runs that used it (the instantiated types and the types that they refer to) |
| `examples/.../omnetpp.ini.json` | `sections`: for each section, the runs whose section chain has it |
| `<path>.json` of another file | `data`: the runs that read or examined the file (only files that git tracks), or that looked it up and did not find it |
| `<folder>/index.json` | the number of runs that used something below the folder, for each kind; `listed`: the runs that listed the folder |
| `runs.json` | for each run: its key, exit code, end, section chain, and `normal_end` |
| `tests.json` | for each test kind and test key: its runs |
| `header.json` | the project, the map commit, the omnetpp commit, the opp_repl commit, the compiler, the enabled features, the date |

A set of runs is `"all"`, `{"except": [run ids]}` if it holds more than half
of the runs, or a list of run ids. Each map file has one JSON value on each
line, so that a git diff of two maps shows one function or one key on each
line.

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

## Limits

- Only the fingerprint tests write records now.
- A run that does not end normally (an exit code other than 0, no profile, or
  no section chain) has `normal_end` false in `runs.json`. Such a run can have
  used inputs that the map does not show, for example NED lookups that failed.
- The file trace sees the calls of the C library that it replaces. A program
  that makes system calls directly is not traced.
- The NED type table does not see the NED lookups that failed in a run.
