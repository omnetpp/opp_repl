# Fix issue #22 — comparisons silently run one commit against itself

GitHub: https://github.com/omnetpp/opp_repl/issues/22

## Problem

`SimulationTask` has no project of its own; it resolves the executable, the working
directory and every result path through `simulation_config.simulation_project`
(`task.py:183,234,252,442,465`, plus `404` for the task hash and `423` for the result
folder). `MultipleSimulationTasks`, by contrast, *does* carry a `simulation_project`
(`task.py:722`) and builds through it (`task.py:744`).

`get_simulation_tasks` short-circuits config discovery when `simulation_configs` is
supplied (`task.py:848-849`), so the explicitly passed `simulation_project` never
reaches the configs. The comparison entry points split `_1`/`_2` kwargs but pass every
unsuffixed kwarg to both sides (`compare.py:785-788`), so one unsuffixed
`simulation_configs` list is handed to both arms.

Net effect: both worktrees are built, both arms run the *configs' own* project, and the
verdict — which starts at `IDENTICAL` and only degrades on a detected difference — comes
back a fully green "no regressions".

Present since the initial commit `ab7b75d` (2026-04-13, inherited from INET); made
invisible by the worktree form in `72f36ab` (2026-04-16). Every tag 0.1.0..0.4 is affected.

## Fixes

- [x] **1. Each side collects its own simulation tasks** (`compare.py`).
      `_get_side_simulation_tasks()` takes the passed `simulation_configs` as naming *which*
      configs to compare, looks the corresponding ones up in that side's own project via
      `SimulationProject.select_simulation_configs()`, and collects the side's tasks from those. Used by both
      `compare_simulations` and `compare_simulations_across_commits`.

- [x] **2. Match the two sides instead of zipping them** (`compare.py`).
      `_match_simulation_tasks()` pairs tasks on
      `(working_directory, ini_file, config, run_number)` and returns the pairs present on
      both sides, warning about the rest. Replaces a bare `zip()`, which silently truncated
      and mis-aligned whenever the two projects exposed different config sets.

- [x] **3. Docs** — `get_simulation_tasks` and `compare_simulations`.

- [x] **4. Regression test** — `opp_repl/test/self/test_compare_binding.py`, runnable
      standalone, no build or simulation needed (7 tests).

## Decisions / notes

- Selection returns the target project's **own** `SimulationConfig` instances, so
  `num_runs`, `sim_time_limit`, `expected_result`, `abstract` and `emulation` are that
  checkout's values. Copying the caller's config onto the target project would run
  commit B's binary with commit A's metadata. Pinned by
  `test_each_arm_gets_its_own_checkouts_config_metadata`.
- `make_worktree_simulation_project` sets `project.simulation_configs = None` on the copy,
  so selection triggers real discovery from that checkout's own `.ini` files.
- Configs present in one checkout but not the other are simply not selected / not matched,
  and are reported via `_logger.warning`. A config added or removed between two commits is
  a normal difference rather than an error; it just cannot be compared. What matters is
  that leaving it out is not *silent*.
- `_select_simulation_configs` forwards `**kwargs` to `get_simulation_configs`, exactly as
  the discovery branch does, so filters and `mode` apply identically on both paths. (Mode
  matters: config discovery inherits the caller's mode.)
- `collect_all_simulation_configs` does not apply `matches_filter` when populating
  `project.simulation_configs`; it globs every ini file and only drops disabled-feature
  folders. So the cached set is always the project's full config set.
- `get_compare_simulations_tasks` / `compare_simulations_using_multiple_tasks` have no
  callers outside `compare.py`.

## Rejected

- **Raising when a config is missing from one side.** Turns a normal cross-commit
  difference into a hard failure; matching plus a warning reports it without refusing to
  run the rest of the comparison.
- **Copying the caller's config onto the target project.** Simpler, but silently carries
  one commit's config metadata into the other's run.
- **Rejecting an unsuffixed `simulation_configs` outright** (the issue's option 2). It is
  an advertised parameter and there is no suffixed alternative; making it work is better
  than making it fail.
