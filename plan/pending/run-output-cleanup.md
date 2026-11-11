# Automatic cleanup of run output

> **Status:** stages 1, 2 and 5 complete, stages 3 and 4 open · **Owner:** opp_repl · **Branch:** `topic/run-output-cleanup`, worktree `opp_repl-run-output-cleanup` · **Optional stages:** INET, OMNeT++ · **Written:** 2026-11-11

opp_repl removes the output of a test or of a comparison when the result is the expected result.
opp_repl keeps the output when the result is not the expected result, because a person will
examine it.

## 1. Why

On 2026-11-11 the disk of the development machine (1.8 TB) was full. The workspace used 469 GB.
338 GB of that were output files that a new run makes again. A manual deletion freed 332 GB.
No tool removes these files, thus they come back with each run and with each new worktree.

Sizes before the manual deletion:

| Class | Maker | Size |
|---|---|---|
| `tests/**/work/` | `opp_test` suites that opp_repl runs | 159 GB in 15 worktrees |
| `results/<config>-#<run>-<1 or 2>.out` | compare functions | 53 GB |
| `results/*.elog` | compare functions and manual runs | 13 GB |
| detached worktrees `<repository>-<ref>` | compare and bisect functions | 54 GB in 15 worktrees |
| `results/*.vec`, `*.sca`, `*.vci`, `*.pcap` | simulation tests and manual runs | 130 GB, not divided |

## 2. What exists today

All line numbers are from opp_repl `main` at `39e15bc` and OMNeT++ `omnetpp-6.x`.

### 2.1 `opp_test` work directories

- `MultipleOppTestTasks.run_protected` deletes `work/` at the start of a suite run
  (`opp_repl/test/opp.py:262-275`). Nothing deletes `work/` at the end.
- `OppTestTask.run_protected` makes `work/<test>/` with a makefile, object files and a binary for
  each test (`opp_repl/test/opp.py:123-153`).
- `opp_test` adds a `_defaults.ini` with `cmdenv-express-mode = false` to each test
  (`python/omnetpp/test.py:218-222` and `374-381`). The full event log goes to `test.out`.
- For each `%contains` block, `opp_test` writes a second full copy of the checked file,
  `test-<key>.out` (`python/omnetpp/test.py:853-856`).
- The 159 GB were 109 GB of output files, 48 GB of binaries and object files, and 2 GB of
  `.subst` copies. One output file was as large as 580 MB.
- No tool reads `work/` after the run. opp_ci, the INET workflows and the INET Python code do not
  refer to it.
- `opp_test` names the folder `work/<test>` after the test file, and it changes each character
  other than a letter, a digit and `_` to `_` (`python/omnetpp/test.py:297-298`). INET has 188
  tests with such a name, for example the packetdrill tests. opp_repl used the name without this
  change (found in stage 1, repaired in `0f2e5ab`).

### 2.2 Result files of the compare functions

- `CompareSimulationsTask.run_protected` turns express mode off and sends stdout to a file
  (`opp_repl/simulation/compare.py:706`).
- Each side writes `results/<config>-#<run>-<index>` with the extensions `.out`, `.elog`, `.sca`
  and `.vec` (`compare.py:684-687`).
- Only the `.vec` file is removed, after its conversion to scalars (`compare.py:580-582`).
- The verdicts for stdout, fingerprint, eventlog and statistics are calculated when the result
  object is made (`compare.py:94-134`). The verdicts for charts and module images are calculated
  later, in `_finalize_chart_comparisons` and `_finalize_module_image_comparisons`. These two
  functions read the result files of all runs.
- `recompare()` reads the stdout files again (`compare.py:236-270`).

### 2.3 Worktrees of the compare and bisect functions

- `_make_git_worktree` makes `<repository>-<git_hash[:10]>` beside the repository
  (`opp_repl/simulation/project.py:1116-1136`). `git_hash` is the text that the caller gives.
- A ref name with a slash thus makes a nested directory. `origin/master` gives
  `inet-master-origin/mas`.
- A directory that exists is used again without a checkout. A worktree with a branch name thus
  stays at its old commit. `inet-master-master` is at a commit from 2026-06-02.
- `delete_worktree=False` is the default of `compare_simulations_between_commits` and
  `compare_simulations_across_commits` (`compare.py:847` and `997`).
- The bisect function makes worktrees and has no removal (`opp_repl/test/bisect.py:132` and `143`).
- Each INET worktree gets its own build output, 4 GB to 5 GB.

### 2.4 Simulation tests

- The smoke, sanitizer, feature and chart tests set no recording option. The validation tests use
  a runner of the project.
- The fingerprint tests turn off only vector and scalar recording
  (`opp_repl/test/fingerprint/task.py:152`). A config that records PCAP files or an eventlog
  continues to write them.
- The statistical tests remove their `.sca`, `.vec` and `.vci` files in
  `check_simulation_task_result` (`opp_repl/test/statistical.py:198-202` and `244`). This function
  runs only when the simulation result is DONE (`opp_repl/test/simulation.py:91-94`). An error, a
  timeout or a cancel leaves the files.
- `SimulationTask.clear_result_folder` removes all `sca`, `vec`, `vci`, `elog`, `log` and `rt`
  files of the result folder (`opp_repl/simulation/task.py:425-430`). It has no caller. It is not
  safe for the shared `results/` folder, because the files of manual runs are there too.
- The module image test uses a result folder of its own and removes it
  (`opp_repl/test/module_image.py:394` and `428-431`).
- INET sets the PCAP file name with `${resultdir}`, thus a PCAP file follows `--result-dir`.

### 2.5 System

- GNOME: `remove-old-trash-files` was `false`. The Trash had 30 GB.
- `/var/tmp` had 53 GB of run copies from agent sessions. 44 GB belong to the account
  `projectured`, and 9.6 GB belong to the account `levy` (15 `claude-*` directories).
- The systemd rule for `/var/tmp` has an age of 30 days, and it works. It removes a file when the
  access time, the change time and the status time are all older than 30 days. On 2026-11-11 no
  file was that old: the last access to the oldest directory was on 2026-10-14.
- Podman had two images without a tag, 2.4 GB together. The large one is a check image for the
  coverage tests from 2026-10-26, not an image of the baseline recipe.

## 3. Design

**One rule:** the tool that makes a file removes the file when the result is the expected result.

**One option:** `keep_output`, with the same meaning in each test type and in the compare
functions. The option goes through `**kwargs`, as the other options do.

| Value | Meaning |
|---|---|
| `"unexpected"` (default) | Keep the output only when the result is not the expected result. |
| `"all"` | Keep all output. Use this value to write or to debug a test. |
| `"none"` | Remove all output. |

"Output" is the work directory of an `opp_test` test, the per-side result files of a comparison,
and the private result folder of a simulation test. Chart images and module images keep their own
options, `keep_charts` and `keep_images`.

**Worktrees** stay for reuse, because a build is slow. opp_repl removes a worktree only when it
has a proof that nobody uses the worktree. The proof has five parts, and each part must be true:

1. **opp_repl made the worktree.** A marker file in the administration directory of the worktree
   (`git rev-parse --git-dir`) records the commit that opp_repl checked out.
2. **No opp_repl process uses it.** A process that makes or uses the worktree again holds a shared
   lock on the marker file until the process ends. The removal needs the exclusive lock and does
   not wait for it. The operating system releases the lock of a process that stops, thus an old
   lock cannot stay.
3. **Nobody worked in it.** `HEAD` is detached at the commit of the marker, and
   `git status --porcelain` is empty. A changed tracked file and a new file that git does not
   ignore are each a sign of work. Build output and result files are ignored files, and they do
   not count.
4. **No other process is in it.** No process of the user has its working directory or an open
   file below the worktree (`/proc` on Linux). When opp_repl cannot do this check, the worktree
   stays.
5. **No run used it for `max_age`** (default 14 days). The time of the marker file gives the last
   use.

When one part is not true or not known, the worktree stays. opp_repl does not touch a worktree
without the marker.

Limit of part 4: opp_repl cannot read the data of the processes of other accounts. The check
thus covers only the processes of the user who runs opp_repl.

## 4. Stages

Do the work in a dedicated worktree. Make one commit for each step. Mark each step when it is
done, and write new facts into this file.

### Stage 1 — `opp_test` work directories (159 GB class)

- [x] 1.0 `OppTestTask.get_test_directory()` gives the folder that `opp_test` makes for the test
      (`0f2e5ab`). This step was not in the first plan. The first INET check found it: the
      folders of the packetdrill tests stayed.
- [x] 1.1 `OppTestTask.run_protected` runs the test in `run_test` and then removes `work/<test>/`
      as `keep_output` tells. `TaskResult.should_keep_output()` makes the decision for all task
      types. A debug run keeps the folder. A dry run does not reach this function (`4424d6a`).
- [x] 1.2 `MultipleOppTestTasks.run_protected`: after the run, remove each `work/` directory that
      is empty (`79b83c0`).
- [x] 1.3 `--keep-output` is an option of all test runners (`adb7f49`).
- [x] 1.4 Self test `opp_repl/test/self/opp.py`, 11 cases, in `opp_repl_self_test`. A stub takes
      the place of `opp_test`, thus the test does not need OMNeT++. The cases fail without the
      change (`4424d6a`, `79b83c0`).
- [x] 1.5 `doc/tasks.md` has a section on the opp tests and `keep_output` (`6a4473e`).

Check, done on 2026-11-11 in `inet-physicallayer-content-errors` (debug, `--no-build`): each
suite ran with the default and with `--keep-output all`, which is the behaviour before the change.

| Suite | Tests | Different verdicts | `work/` with the default | `work/` with `all` |
|---|---|---|---|---|
| protocol | 1193 | 0 | 1.5 GB | 23.3 GB |
| module | 849 | 0 | 0 | 3.1 GB |
| unit | 155 | 0 | 0 | 1.6 GB |

The 1.5 GB are the folders of the 67 tests with an unexpected FAIL. An expected FAIL (47 tests)
and a SKIP (306 tests) leave no folder.

Note: the disk use during a run is now the number of parallel tests multiplied by the size of one
test, a maximum of about 1.2 GB for each test.

### Stage 2 — result files of the compare functions (53 GB class)

- [x] 2.1 `CompareSimulationsTaskResult.get_output_file_paths()` gives the `.out`, `.elog`, `.sca`,
      `.vec` and `.vci` files of the two sides, and `_remove_output_files()` removes them
      (`a54bdba`).
- [x] 2.2 The two entry points that do the chart and module image steps call
      `_remove_output_files()` after these steps: `compare_simulations_using_multiple_tasks` and
      `compare_simulations_across_commits`. With the default, a comparison with the result
      IDENTICAL removes its files (`a54bdba`).
- [x] 2.3 `recompare()` raises an error that names `keep_output="all"` when the files are removed.
      The result records this in `output_files_removed`. The trajectory functions did not change
      (`a54bdba`).
- [x] 2.4 Self test `opp_repl/test/self/compare.py`, 8 cases, in `opp_repl_self_test`. It builds
      and runs no simulation (`a54bdba`).
- [x] 2.5 `doc/comparing_simulations.md` has a section on the output file cleanup (`a8a4957`).

Facts from the work:

- A comparison that did not run its simulations (a dry run, a cancel) removes no file. The files
  on the disk are then from an earlier run.
- A file that some other comparison keeps stays. Two pairs of a comparison across commits can
  write the same file of one commit, for example in the baseline mode.
- The `.vci` file stayed after each comparison before this change, because the conversion of the
  vectors removed only the `.vec` file.

Check, done on 2026-11-11 with real simulations (`examples/inet/nclients`, config `inet__inet`,
2 s, the two sides in one project):

| Case | Result | Files in `results/` after the run |
|---|---|---|
| same seed, default | IDENTICAL | none |
| same seed, `keep_output="all"` | IDENTICAL | 8 files, 6.5 MB |
| other seed on side 2, default | DIVERGENT | 8 files, 7.4 MB; `recompare()` works |
| other seed on side 2, `keep_output="none"` | DIVERGENT | none |

### Stage 3 — worktrees (54 GB class)

- [ ] 3.1 `_make_git_worktree`: change the ref to the commit hash with `git rev-parse`, then make
      the name from the hash. This step also repairs the old checkout for a branch name.
- [ ] 3.2 Write a marker file with the commit into the administration directory of the worktree
      (`git rev-parse --git-dir`). Update its time at each use. Hold a shared lock on it while the
      process has the worktree as a project.
- [ ] 3.3 Add `is_worktree_unused(worktree_path, max_age)`. It gives the five parts of the proof
      of section 3 and the part that is not true.
- [ ] 3.4 Add `remove_unused_worktrees(simulation_project, max_age="14d")`. It removes each
      worktree for which the proof is complete, and it logs the reason for each worktree that
      stays. `_make_git_worktree` calls it before it adds a worktree.
- [ ] 3.5 `delete_worktree=True` and the bisect function use the same proof, without part 5.
- [ ] 3.6 Add a self test with a temporary repository: the name from a ref with a slash, the
      reuse, and one case for each part of the proof.
- [ ] 3.7 One time, by hand: list the 15 old worktrees without a marker, and remove them after the
      user agrees.

### Stage 4 — simulation tests (part of the 130 GB class)

- [ ] 4.1 Measure first. In a clean INET worktree, run the smoke, sanitizer, fingerprint,
      statistical and chart tests on a small filter. Record the files that stay in `results/` for
      each test type. Do not run the feature tests on this machine.
- [ ] 4.2 Statistical tests: move the removal of the `.sca`, `.vec` and `.vci` files into a
      `finally` block, thus it runs for each simulation result.
- [ ] 4.3 Tests that do not read results in `results/`: `SimulationTestTask` gives the simulation
      task a private result folder, `results/<test type>-<pid>/<config>-<run>/`, and removes it
      after the check as `keep_output` tells. Use the list of test types from step 4.1.
- [ ] 4.4 Chart tests: decide after step 4.1. The charts read `results/` in place, thus a private
      folder is not possible. A possible rule is to remove the result files of a directory when
      all its charts pass.

Check for step 4.3: the fingerprint results of the full INET suite are the same as before. A
config with a fixed `results/` path in its ini file is a risk.

### Stage 5 — system settings (no code, each step needs the user's agreement)

- [x] 5.1 Trash: `gsettings set org.gnome.desktop.privacy remove-old-trash-files true`. The age
      is 30 days already. Done on 2026-11-11.
- [x] 5.2 `/var/tmp`: examined on 2026-11-11, no change. The 30-day rule works (section 2.5). A
      shorter age can remove the run copy of a task that continues for more than some days. The
      directories of the account `projectured` are not in the scope of this plan.
- [x] 5.3 `podman image prune -f` is in the baseline update recipe
      (`ghci-statistical/tools/README.md`), after the build of a new image. The two images
      without a tag are not removed. They are not from this recipe.

### Optional stages in other repositories

These stages decrease the disk use during a run and the run time. Stage 1 removes the files
without them.

- [ ] O1 INET: set `cmdenv-express-mode = true` in the shared ini files of the large protocol
      tests. Measure the size of `test.out` for each test first. 825 of the 1193 protocol tests
      check a `PROTOCOLTEST <name>: PASS` line, and `ProtocolTester` prints this line on
      `std::cout` (`tests/protocol/lib/ProtocolTester.cc:892`). 32 tests in `tests/protocol/element`
      set express mode already. Tests that check log lines must keep the log.
- [ ] O2 OMNeT++: `opp_test` writes `test-<key>.out` only when the check fails.

## 5. Delivery

- Land the stages on opp_repl `main`, one stage after the other. Run `opp_repl_self_test` for each
  stage.
- Bring the `github_ci` and `opp_ci` branches up to date only when the user asks.
- Move this file to `plan/done/` when the stages 1 to 5 are complete.

## 6. Decisions

| # | Decision | Result |
|---|---|---|
| D1 | Name and values of the option | `keep_output` with `"unexpected"`, `"all"`, `"none"` |
| D2 | Worktrees: when to remove | Only with a proof that nobody uses the worktree (section 3) |
| D3 | System settings of stage 5 | 5.1 and 5.3 done; 5.2 examined, no change |
| D4 | Optional stages O1 and O2 | Later, after a measurement |

## 7. Out of scope

- The `out/` build directories (93 GB). They go away when a worktree is removed.
- The validation tests. The runner is in the project, not in opp_repl. Their results were 0.5 GB.
- The compiler cache. It has a limit of 5 GB.
- Result files of manual runs. The user owns them.

## 8. Decision log

| Date | Decision |
|---|---|
| 2026-11-11 | Plan written. |
| 2026-11-11 | User: D1 agreed. D2: remove a worktree only when it is provably not in use. D3 agreed. D4 later. |
| 2026-11-11 | D2: the proof has five parts (section 3). The user has not yet confirmed this definition of the proof. |
| 2026-11-11 | 5.2: no new `/var/tmp` rule, because the 30-day rule of the system works. |
| 2026-11-11 | Stage 1: a test with an expected FAIL or a SKIP also loses its folder, because the result is the expected result. |
| 2026-11-11 | Stage 1: `should_keep_output()` is a method of `TaskResult`, thus stages 2 and 4 use the same decision. |
| 2026-11-11 | Stage 2: the guard is in `recompare()` and not in the trajectory functions, because other callers also use these functions. |
