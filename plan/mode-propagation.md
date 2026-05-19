# opp_repl `mode` parameter propagation audit

Audit of how the build/run `mode` parameter (`"release"`, `"debug"`,
`"sanitize"`, `"coverage"`, `"profile"`) flows through opp_repl's task,
test, update, and comparison machinery. Findings are grouped by severity.
Each item references a `file:line` location, describes the bug, and
suggests the minimal fix.

The general failure modes are:

- The same logical operation builds with one mode and runs with another
  (build/run mismatch), so users hit "executable not found" or run the
  wrong binary.
- A user-supplied `mode` is silently dropped on the way down, so
  everything defaults to `"release"` regardless of the request.
- Update flows skip the build step that the parallel test flows perform.

## Critical (build/run mismatch or `mode` silently dropped)

1. **`opp_repl/test/simulation.py:102` and `opp_repl/test/simulation.py:123-126`**
   — `MultipleSimulationTestTasks` defaults `mode="debug"` while the
   inner `SimulationTask` objects are produced by
   `get_simulation_tasks(**kwargs)` which defaults to `"release"`
   (`opp_repl/simulation/task.py:762-763`). When the user calls
   `run_smoke_tests`/`run_statistical_tests`/`run_fingerprint_tests`/
   `run_chart_tests`/`run_simulation_tests` *without* an explicit `mode`,
   `build_before_run` (`opp_repl/test/simulation.py:115-116`) builds in
   `debug`, then each `SimulationTask` tries to launch `opp_run_release`.
   Fix: in `get_simulation_test_tasks`, forward
   `mode=multiple_simulation_tasks.mode` (and `build`, `build_mode`) into
   the `MultipleSimulationTestTasks` constructor so the per-task mode
   and the wrapper mode always agree. Same default change should be
   considered for `MultipleSimulationTestTasks.__init__`.

2. **`opp_repl/simulation/task.py:416` and `opp_repl/simulation/task.py:439`**
   — `SimulationTask.is_interactive` and `_resolve_output_file_path` call
   `simulation_project.get_executable()` with no `mode` argument, so
   they always resolve to release. Both are instance methods on a
   `SimulationTask` that has `self.mode`; the third call site on
   `:506` already passes `mode=self.mode` correctly. Fix: pass
   `mode=self.mode` in both calls.

3. **`opp_repl/test/simulation.py:185-194`** —
   `MultipleSimulationUpdateTasks` has no `mode` / `build` /
   `build_mode` / `build_before_run`, unlike its test sibling
   (`opp_repl/test/simulation.py:101-121`). `update_statistical_test_results`
   (`opp_repl/test/statistical.py:354-369`) goes through this class and
   therefore never auto-builds.
   `update_fingerprint_test_results` partially compensates by overriding
   `MultipleFingerprintUpdateTasks.run`
   (`opp_repl/test/fingerprint/task.py:374-380`), but only by forwarding
   the *current* `**kwargs` to `build_project`; the mode is not stored
   on the object. Fix: lift the `mode`/`build`/`build_mode`/
   `build_before_run` machinery into a shared base
   (e.g. `MultipleSimulationTasks` already has it) or duplicate it on
   `MultipleSimulationUpdateTasks`, and rewrite
   `MultipleFingerprintUpdateTasks.run` to call
   `self.build_before_run(**kwargs)`.

4. **`opp_repl/test/feature.py:71-73` and `opp_repl/test/feature.py:46`, `:50`**
   — `FeatureTestTask.run_protected` calls
   `make_makefiles(simulation_project=...)`,
   `clean_project(simulation_project=...)`,
   `build_project(simulation_project=...)` with no `mode`, so they
   always operate on release. `get_multiple_simulation_tasks` also
   calls `get_simulation_tasks(...)` with no mode. A user-requested
   `mode="debug"` (or sanitize) is silently dropped. Fix: store
   `self.mode` (from kwargs, default release) on the task and forward
   it to `clean_project`, `build_project`, and `get_simulation_tasks`.

5. **`opp_repl/simulation/project.py:825-833`** —
   `SimulationProject.collect_all_simulation_configs` hardcodes
   `self.build(mode="release", build_mode=build_mode)`. Config discovery
   triggers a release build even when the rest of the pipeline wants
   debug/sanitize. Fix: accept `mode` (default `"release"`) on the
   method and thread it from `get_simulation_configs` /
   `get_all_simulation_configs`; `get_simulation_tasks` already has
   `mode` in scope at the call site.

6. **`opp_repl/simulation/project.py:733` and `opp_repl/simulation/project.py:740`**
   — `SimulationProject.get_num_runs_in_config` hardcodes
   `get_executable(mode="release")` in both branches. Config discovery
   fails for projects that are only built in debug/sanitize. The call
   chain (`get_simulation_configs` → `get_all_simulation_configs` →
   `collect_all_simulation_configs` → `collect_ini_file_simulation_configs`
   → `get_num_runs_in_config`) carries `**kwargs` but the mode is
   dropped at every hop. Fix: add a `mode` parameter to
   `get_num_runs_in_config` and propagate it.

7. **`opp_repl/simulation/build.py:778-811`** —
   `CleanSimulationProjectTask.get_clean_tasks` accepts `mode` but
   constructs the binary paths as
   `os.path.join(bin_folder, executable)` and `"lib" + library + ".so"`,
   ignoring the `_dbg`/`_sanitize`/`_profile` suffix that
   `SimulationProjectCopyBinaryTask` applies
   (`opp_repl/simulation/build.py:578-588`). `clean_project_using_tasks(mode="debug")`
   leaves the debug binaries on disk. Fix: replicate the prefix/suffix/
   extension logic from `SimulationProjectCopyBinaryTask` (ideally
   factor it into a helper used by both).

## Medium (inconsistent state, not currently incorrect)

8. **`opp_repl/test/fingerprint/task.py:374-380`** —
   `MultipleFingerprintUpdateTasks.run` rebuilds via
   `build_project(simulation_project=simulation_project, **kwargs)`.
   `mode` only takes effect if the caller passed it through `kwargs`
   on *this* `run()` call. There's no `self.mode` on the multiple-tasks
   object the way `MultipleSimulationTasks` has it. Re-running the
   same task object without kwargs silently builds release. Fix: see
   item 3 (lift `mode` onto the multiple-update-tasks base class).

9. **`opp_repl/test/feature.py:78-96`** — `MultipleFeatureTestTasks`
   inherits from `MultipleTestTasks` and skips
   `MultipleSimulationTestTasks`, so it has no mode-aware
   `build_before_run`. When invoked via `get_all_test_tasks` /
   `run_all_tests` (`opp_repl/test/all.py`), there is no top-level
   build at all — every `FeatureTestTask.run_protected` does its own
   (mode-less, item 4) build per iteration. Fix: after item 4, also
   give `MultipleFeatureTestTasks` a `build_before_run` that builds
   the project once in the requested mode, then keep the per-iteration
   feature toggles.

10. **`opp_repl/test/profile.py:15`** —
    `generate_profile_report` calls
    `run_simulations(simulation_project=..., mode="profile", ...)`.
    The `_profile` library suffix flows correctly through
    `SimulationProject.get_executable` / `OmnetppProject.get_library_suffix`
    (`opp_repl/simulation/project.py:123-124`), so the run picks up
    `opp_run_profile`. This is functional, but worth noting because
    there is no smoke test for the profile-mode build, and any future
    change to `_simulation_project_output_folder` /
    `get_library_suffix` could silently break this path.

## Minor / hygiene

11. **`opp_repl/test/simulation.py:102` vs `opp_repl/simulation/task.py:634`, `:277`, `:699-701`**
    — Docstring/default inconsistency: `MultipleSimulationTestTasks`
    defaults to `"debug"`, while `MultipleSimulationTasks`,
    `SimulationTask`, and the `get_simulation_tasks` docstring all say
    `"release"`. After item 1, document the intentional choice (or
    align the defaults).

12. **`opp_repl/simulation/task.py:699-701`** — Docstring for
    `get_simulation_tasks` lists only `"debug"` and `"release"` as
    valid `mode` values, but `SimulationTask.__init__`
    (`opp_repl/simulation/task.py:292-293`) also accepts `"sanitize"`,
    `coverage.py` uses `"coverage"`, and `profile.py` uses `"profile"`.
    Update the docstring to mention all supported modes.

## Suggested rollout

- Land items 1 and 2 first — they affect every default test run.
- Land item 3 next; it unblocks update flows. Item 8 is a free win
  inside the same refactor.
- Items 4 and 9 are coupled — fix the per-task mode threading in
  `FeatureTestTask` and add a wrapper `build_before_run` together.
- Items 5 and 6 are coupled — they share the
  `collect_all_simulation_configs` → `get_num_runs_in_config` chain.
- Item 7 is independent and small; ship it whenever convenient.
- Items 10-12 are documentation / hardening; fold them into the
  earlier PRs.
