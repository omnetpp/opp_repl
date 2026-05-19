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
   `mode=multiple_simulation_tasks.mode` (and `build`, `build_engine`) into
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
   `build_engine` / `build_before_run`, unlike its test sibling
   (`opp_repl/test/simulation.py:101-121`). `update_statistical_test_results`
   (`opp_repl/test/statistical.py:354-369`) goes through this class and
   therefore never auto-builds.
   `update_fingerprint_test_results` partially compensates by overriding
   `MultipleFingerprintUpdateTasks.run`
   (`opp_repl/test/fingerprint/task.py:374-380`), but only by forwarding
   the *current* `**kwargs` to `build_project`; the mode is not stored
   on the object. Fix: lift the `mode`/`build`/`build_engine`/
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

5. **`opp_repl/simulation/build.py:778-811`** —
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

6. **`opp_repl/test/fingerprint/task.py:374-380`** —
   `MultipleFingerprintUpdateTasks.run` rebuilds via
   `build_project(simulation_project=simulation_project, **kwargs)`.
   `mode` only takes effect if the caller passed it through `kwargs`
   on *this* `run()` call. There's no `self.mode` on the multiple-tasks
   object the way `MultipleSimulationTasks` has it. Re-running the
   same task object without kwargs silently builds release. Fix: see
   item 3 (lift `mode` onto the multiple-update-tasks base class).

7. **`opp_repl/test/feature.py:78-96`** — `MultipleFeatureTestTasks`
   inherits from `MultipleTestTasks` and skips
   `MultipleSimulationTestTasks`, so it has no mode-aware
   `build_before_run`. When invoked via `get_all_test_tasks` /
   `run_all_tests` (`opp_repl/test/all.py`), there is no top-level
   build at all — every `FeatureTestTask.run_protected` does its own
   (mode-less, item 4) build per iteration. Fix: after item 4, also
   give `MultipleFeatureTestTasks` a `build_before_run` that builds
   the project once in the requested mode, then keep the per-iteration
   feature toggles.

8. **`opp_repl/test/profile.py:15`** —
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

9. **`opp_repl/test/simulation.py:102` vs `opp_repl/simulation/task.py:634`, `:277`, `:699-701`**
   — Docstring/default inconsistency: `MultipleSimulationTestTasks`
   defaults to `"debug"`, while `MultipleSimulationTasks`,
   `SimulationTask`, and the `get_simulation_tasks` docstring all say
   `"release"`. After item 1, document the intentional choice (or
   align the defaults).

10. **`opp_repl/simulation/task.py:699-701`** — Docstring for
    `get_simulation_tasks` lists only `"debug"` and `"release"` as
    valid `mode` values, but `SimulationTask.__init__`
    (`opp_repl/simulation/task.py:292-293`) also accepts `"sanitize"`,
    `coverage.py` uses `"coverage"`, and `profile.py` uses `"profile"`.
    Update the docstring to mention all supported modes.

## Post-fix rules and defaults

After this plan is applied, the three orthogonal parameters behave as
follows. They are **not** synonyms (see `build_engine` note); the audit
is only about `mode`, but recording the full picture here keeps future
edits honest.

### `build` (bool) — *whether* to build before running

- **Default:** `get_default_build_argument()`
  (`opp_repl/simulation/build.py`); typically `True`.
- **Stored on:** `MultipleSimulationTasks`, `MultipleSimulationTestTasks`,
  `MultipleSimulationUpdateTasks` (added by item 3),
  `MultipleFeatureTestTasks` (added by item 7).
- **Rule:** if truthy, `build_before_run` is invoked before
  `run_protected`; if falsy, the build step is skipped. Individual
  `SimulationTask.run` calls never trigger their own build — only the
  multiple-tasks wrappers do.

### `build_engine` (str) — *how* the build is driven

- **Values:** `"makefile"` (drives `make` via `opp_makemake`-generated
  Makefile), `"task"` (drives the per-file `MsgCompileTask` /
  `CppCompileTask` / `LinkTask` pipeline).
- **Default:** `get_default_build_engine()`
  (`opp_repl/simulation/build.py:21-29`); currently `"makefile"`.
  Settable globally via `set_default_build_engine`.
- **Stored on:** same wrappers that store `build`. Forwarded by
  `SimulationProject.build` / `clean` into `build_project` /
  `clean_project`, which dispatch on it
  (`opp_repl/simulation/build.py:119-146`).
- **Rule:** orthogonal to `mode`. A `mode="debug"` simulation can be
  built with either `build_engine="makefile"` or `build_engine="task"`;
  the resulting artifact is the same `_dbg` binary.

### `mode` (str) — *which artifact flavor* to build/run

- **Values:** `"release"`, `"debug"`, `"sanitize"`, `"coverage"`,
  `"profile"`. (Item 10: docstring update so this list is canonical.)
- **Defaults:**
  - `SimulationTask`, `MultipleSimulationTasks`: `"release"`.
  - `get_simulation_tasks`: `None` → resolves to `"debug"` if `debug`
    is truthy (or any of `break_at_event_number` /
    `break_at_matching_event` are set), else `"release"`.
  - `MultipleSimulationTestTasks` and subclasses
    (`MultipleSmokeTestTasks`, `MultipleFingerprintTestTasks`,
    `MultipleStatisticalTestTasks`, `MultipleChartTestTasks`,
    `MultipleOppTestTasks`): `"debug"` — assertions on, better stack
    traces, intentional choice. Documented after item 9.
  - `MultipleSimulationUpdateTasks` and subclasses (added by item 3):
    `"debug"` — matches the test side.
  - `get_sanitizer_test_tasks`: `"sanitize"`.
  - `generate_coverage_report`: `"coverage"`.
  - `generate_profile_report`: `"profile"`.
- **Invariants (enforced by items 1, 3, 4):**
  - For any wrapper, **the per-task `mode` equals the wrapper's
    `mode`.** `get_simulation_test_tasks` / its update sibling /
    `FeatureTestTask` resolve `mode` once and forward the *same*
    value to both `get_simulation_tasks` and the wrapper
    constructor, so `build_before_run` and the launched executable
    can no longer disagree.
  - `SimulationTask`-level helpers (`is_interactive`,
    `_resolve_output_file_path`, item 2) use `self.mode`, not
    `"release"`.
  - Config discovery (`collect_all_simulation_configs`,
    `get_num_runs_in_config`) inherits the caller's mode rather than
    hardcoding release. See the note below.
- **Explicit user override:** passing `mode=...` at any top-level
  entry point (`run_simulations`, `run_*_tests`,
  `update_*_test_results`, `compare_*`) propagates all the way down;
  no intermediate layer overwrites it.

## Note on config discovery

`SimulationProject.collect_all_simulation_configs` and
`SimulationProject.get_num_runs_in_config` now thread the caller's
`mode` through (changed from the earlier always-release behavior). The
implicit pre-discovery build and the `-q numruns` probe both use the
mode requested by the caller (e.g. `run_simulations(mode="debug")` does
discovery against the debug build, not release). Mode parameter
defaults to `"release"` when called bare (e.g.
`inet_project.get_simulation_configs()`).

## Documentation updates

Building is currently explained piecemeal across several guides; after
items 1–10 land, the post-fix rules above should be captured in one
canonical place so the doc/code skew that triggered this audit doesn't
recur.

### New guide: `doc/building.md`

Add a dedicated guide covering how opp_repl builds OMNeT++ and
simulation projects. Suggested sections (mirroring the structure of
the existing `doc/running_simulations.md`):

1. **Three orthogonal parameters** — short table identical to the
   "Post-fix rules" section above (`build`, `mode`, `build_engine`),
   with one example per axis. Pitch this as the first thing a reader
   sees because the names are confusable.
2. **What gets built when** — when `build_before_run` fires, what
   `MultipleSimulationTasks` / `MultipleSimulationTestTasks` /
   `MultipleSimulationUpdateTasks` do automatically, when to call
   `build_project` / `SimulationProject.build` manually, and the
   `build=False` escape hatch.
3. **Build modes (artifact flavors)** — the `mode` axis. One
   paragraph each for `release` / `debug` / `sanitize` / `coverage` /
   `profile`, with the binary suffix and the typical use case.
   Document the per-wrapper default table (test wrappers default to
   `"debug"`, simulation wrappers default to `"release"`, sanitizer
   defaults to `"sanitize"`, etc.) and the explanation of *why* the
   test side prefers debug.
4. **Build engines** — the `build_engine` axis. Explain the difference
   between `"makefile"` (drives `make` via opp_makemake-generated
   Makefile) and `"task"` (per-file `MsgCompileTask` / `CppCompileTask`
   / `LinkTask`). Cover `get_default_build_engine` /
   `set_default_build_engine` and when one engine is preferable
   (e.g. task engine for finer-grained progress, makefile engine for
   parity with command-line `make`).
5. **Recursive builds** — `SimulationProject.build(recursive=True)`
   building OMNeT++ first, then used projects, then self
   (`opp_repl/simulation/project.py:669-683`). Note that
   `used_projects` short-circuits the direct OMNeT++ step
   (`:679-681`) — a subtlety that has caused confusion.
6. **Cleaning** — `clean_project`, `SimulationProject.clean`. Same
   `mode` / `build_engine` axes apply. After item 5, document that
   cleaning in non-release modes now removes the suffixed binaries.
7. **Build artifacts on disk** — `out/clang-{mode}/` vs
   `out/{makefile_inc.configname}/`, `bin/`, `lib/`. Explain the
   `_dbg` / `_sanitize` / `_profile` / `_release` suffixes and what
   `get_executable(mode=...)` returns.
8. **Overlay builds** — one paragraph plus a link to the existing
   [Overlay builds](overlay_builds.md) guide.
9. **opp_env workspaces** — one paragraph on how `opp_env_workspace` /
   `opp_env_project` reroute `build` / `clean` / `run`.
10. **Config discovery** — short note that config discovery always
    uses release (see "Out of scope" above), so a project must have
    at least a release binary available for `get_simulation_configs`
    to work, and explain *why* (it's a `-q numruns` probe).

### Cross-references to update

- **`doc/overview.md`** — add `building.md` to the table of contents.
- **`doc/running_simulations.md:94-109`** — replace the inline
  "Building is implicit…" block with a pointer to `building.md`. Keep
  the one-line "pass `build=False` to skip" hint.
- **`doc/tasks.md:131-186`** ("Build modes" subsection) — collapse
  into a one-paragraph summary + link to `building.md`. The current
  duplication of the mode table is one of the places item 10
  (docstring update) needs to keep in sync.
- **`doc/omnetpp_projects.md:54-75`** ("Build modes" subsection) —
  same: keep the executable-resolution table (it's OMNeT++-specific),
  but defer the general mode explanation to `building.md`.
- **`doc/simulation_projects.md:179-189`** ("Building" subsection) —
  same treatment.
- **`doc/concepts.md`** — add `mode` / `build_engine` / `build` to the
  concept glossary, each as a one-line entry that links into
  `building.md`.
- **`doc/sanitizer_tests.md`**, **`doc/coverage.md`**,
  **`doc/profiling.md`** — verify each mentions the `mode` default
  it imposes (`"sanitize"`, `"coverage"`, `"profile"`) and links to
  `building.md` for the artifact-suffix table.
- **`doc/cluster.md`** — its `--mode` flag examples should reference
  `building.md` once for the value list.

### Docstrings touched by item 10

After updating the `get_simulation_tasks` docstring, sweep these for
the same list (so the single source of truth is `building.md`, and
the docstrings just enumerate accepted values):

- `SimulationTask.__init__` mode docstring
  (`opp_repl/simulation/task.py:292-293`).
- `MultipleSimulationTasks.__init__` mode docstring
  (`opp_repl/simulation/task.py:639-640`).
- `SimulationProject.build` / `.clean` and
  `OmnetppProject.build` / `.clean` docstrings
  (`opp_repl/simulation/project.py:176-238`,
  `:669-714`).
- `build_project_using_makefile` docstring
  (`opp_repl/simulation/build.py:176-191`).
- `get_library_suffix` docstring
  (`opp_repl/simulation/project.py:114-126`) — currently no docstring;
  add a one-line entry now that the canonical list lives in the new
  guide.

## Suggested rollout

- Land items 1 and 2 first — they affect every default test run.
- Land item 3 next; it unblocks update flows. Item 6 is a free win
  inside the same refactor.
- Items 4 and 7 are coupled — fix the per-task mode threading in
  `FeatureTestTask` and add a wrapper `build_before_run` together.
- Item 5 is independent and small; ship it whenever convenient.
- Items 8-10 are documentation / hardening; fold them into the
  earlier PRs.
- Write `doc/building.md` last, after the code changes have settled,
  so the doc reflects the post-fix invariants rather than the
  in-flight state. Do the cross-reference sweep in the same PR.
