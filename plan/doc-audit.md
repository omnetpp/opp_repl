# opp_repl documentation audit

Audit of the ~30 doc files in `doc/` for self-consistency and consistency
with the source under `opp_repl/`. Findings are grouped by severity.
Each item references a `file:line` location and states what is wrong and
what it should say.

## Critical (broken examples or absent code)

1. **doc/running_simulations.md:54** — Example calls `r.get_fail_results().rerun()`,
   but `MultipleSimulationTaskResults` only defines `get_error_results()`.
   `get_fail_results()` is defined only on `MultipleTestTaskResults`
   (`opp_repl/test/task.py:50`). Replace with `r.get_error_results().rerun()`,
   matching `doc/task_results.md:399`.

2. **doc/tasks.md:211-212** — Says `clean_simulation_results()` "removes
   `.sca`, `.vec`, `.vci`, `.elog`, `.log`, `.rt` files". Actually
   `SimulationConfig.clean_simulation_results` (`opp_repl/simulation/config.py:143-150`)
   does `shutil.rmtree(results/)` — it deletes the whole `results/` folder.
   The selective per-extension cleanup is `SimulationTask.clear_result_folder()`
   (`opp_repl/simulation/task.py:398`), a different method.
   `doc/running_simulations.md:138-139` already describes it correctly,
   so the two docs contradict each other.

3. **doc/cluster.md:91** — Example calls
   `p.copy_binary_simulation_distribution_to_cluster([...])`, but no such
   method is defined on `SimulationProject`. The same call appears in
   `opp_repl/main.py:86`, so the `--hosts` CLI path is also broken. Either
   add the method or remove the example and CLI flow.

4. **doc/cluster.md:151-153** — Claims "exiting the Python session
   automatically stops the SSH cluster". `opp_repl/common/cluster.py`
   registers no `atexit`/`__del__` hook. Implement it or drop the
   paragraph.

5. **doc/cluster.md:5** — Says the `cluster` extra installs `dask` +
   `dask.distributed`. `pyproject.toml:49-52` lists `dask` + `distributed`
   (the PyPI package is `distributed`).

6. **doc/smoke_tests.md / doc/comparison_tests.md** — Use
   `get_failed_results()` / iterate `get_fail_results()` directly. Only
   `get_error_results()` exists on the relevant result classes.

7. **doc/statistical_tests.md** — Uses kwarg `relative_error_threshold=`.
   The actual parameter name in the function signature differs;
   verify in `opp_repl/simulation/fingerprint.py` and
   `opp_repl/test/statistical.py`.

8. **doc/installation.md:17-19** — Says "two mandatory dependencies —
   IPython and pandas". `pyproject.toml:15-20` lists four:
   `ipython`, `pandas`, `matplotlib`, `numpy`. Either update prose to
   four, or move `matplotlib`/`numpy` to optional extras.

9. **doc/installation.md vs README.md:14** — README says
   `pip install opp_repl`; installation.md only documents the
   git-clone + editable install path. Reconcile (either add a
   `pip install opp_repl` quick path to installation.md, or note in
   README that the package is not on PyPI yet).

10. **doc/repl.md:14-26** — Omits the security-relevant
    `--mcp-token-hash` flag entirely, despite documenting `--mcp-port`.
    Also: `--mcp-port` default is `0` (disabled); call this out
    explicitly. REPL default log level is `INFO`
    (`opp_repl/repl.py:30`), while CLI tools default to `WARN`
    (`opp_repl/main.py:51`) — flag the asymmetry.

11. **doc/mcp_server.md:50-53 — sandbox sentinel** — *Resolved: non-issue.*
    `bin/opp_sandbox` does bind-mount the sentinel:
    `--ro-bind "$OMNETPP_ROOT/bin/opp_sandbox" "/.opp_sandbox"`.
    `is_running_in_sandbox()` correctly detects it (existence + writable
    check). The audit was mistaken.

## Important

12. **doc/overview.md command-line tools list** — Missing `opp_mount`,
    `opp_unmount`, `opp_build_omnetpp`, `opp_build_project`,
    `opp_clean_omnetpp`, `opp_clean_project`. All are defined in
    `pyproject.toml:79-100`.

13. **doc/opp_files.md:65-91 (SimulationProject parameter table)** —
    Omits ~20 parameters actually used by bundled `.opp` files:
    `image_folders`, `include_folders`, `cpp_folders`, `cpp_defines`,
    `msg_folders`, `dll_symbol`, `feature_libraries`,
    `opp_defines_file`, `extra_cflags`, `extra_ldflags`,
    `external_bin_folders`, `external_library_folders`,
    `external_libraries`, `external_include_folders`,
    `precompiled_header`, `simulation_configs`, `git_hash`,
    `git_diff_hash`, `static_libraries`, `python_folders`,
    `dependency_store`. Cf. `inet.opp:11-28`.

14. **doc/opp_files.md:76** — Says `dynamic_libraries` / `executables`
    default to `None`. Effective default is `[name]`
    (`opp_repl/simulation/project.py:470-471`). Document the
    "`None` means `[name]`" behavior, or list `[name]` as the default.

15. **doc/opp_files.md:30-36** — Implies `OmnetppProject` and
    `SimulationProject` behave the same for "Locating the Project Root".
    They do not: `OmnetppProject.root_folder_environment_variable`
    defaults to `"__omnetpp_root_dir"`, while `SimulationProject`
    defaults to `None`.

16. **doc/simulation_workspaces.md:78-100** — Describes
    default-OMNeT++-project logic without the "only set if currently None"
    guard in `opp_repl/simulation/workspace.py:131-138`. A user who
    explicitly chose a non-default OMNeT++ project and later calls
    `set_default_simulation_project()` won't see the doc's described
    behavior.

17. **doc/parameter_optimization.md:92-110** — Parameter table omits
    `simulation_runner` and `**kwargs` forwarding to
    `simulation_task.run()` (cf. `opp_repl/simulation/optimize.py:84-85`).

18. **doc/bisecting.md** — Never mentions `update_good_results`
    (default `True`) which appears in every wrapper. Also:
    `bisect_smoke_tests` (`opp_repl/test/bisect.py:279-282`) and
    `bisect_sanitizer_tests` (`bisect.py:330-333`) never pass
    `update_good_results_function`, so the flag is silently inert for
    those — fix code, or document the gap.

19. **doc/github_actions.md:60** — Says "Bearer token".
    `opp_repl/common/github.py:36-40` uses the `Authorization: token <token>`
    scheme. Fix the doc (or switch the code to Bearer).

20. **doc/chart_tests.md:17-19 and doc/feature_tests.md:141** —
    *Resolved: non-issue.*  The audit was written against an older
    pyproject where matplotlib was mandatory.  Currently matplotlib is
    in the optional `chart` extra (`pyproject.toml:53-56`), so the
    "if matplotlib is installed" hedge is correct.

21. **doc/comparing_simulations.md:176-179** — *Resolved: non-issue.*
    The asymmetric kwarg names cited by the audit
    (`statistical_result_name_filter` vs `exclude_statistic_name_filter`)
    no longer exist in the source or docs.  The current code/doc uses
    `result_name_filter` / `exclude_result_name_filter` consistently.

22. **Fingerprint test code bugs surfaced by the audit** —
    `MultipleFingerprintTestTaskResults.__init__` is misspelled `__init`
    in the source. Also, `MultipleSpeedUpdateTasks.run` returns the store
    rather than the results object. These are real code bugs, not doc
    bugs, but they invalidate doc claims.

23. **Speed / statistical update class names** — *Resolved: non-issue.*
    Verified: doc names match source.  `StatisticalResultsUpdateTask`
    (statistical.py:282), `SpeedUpdateTask` (speed/task.py:93), and
    `SpeedUpdateTaskResult` (speed/task.py:137) all exist with these
    exact names.

24. **doc/statistical_tests.md reason strings** — Example failure-reason
    strings don't match what the code emits on assertion failure.

## Minor

25. **doc/omnetpp_projects.md:13-15** — Example sets
    `root_folder_environment_variable="__omnetpp_root_dir"`, which is
    already the default — misleading.

26. **doc/omnetpp_projects.md examples** — *Resolved: code fix.*
    `OmnetppProject.__init__` now accepts `name=`, matching
    `SimulationProject` and the doc examples.  Direct Python use of
    `OmnetppProject(name=..., ...)` no longer raises `TypeError`.

27. **doc/overlay_builds.md:124-128** — `project.clean()` "unmounts and
    removes upper/work" only applies to overlay-backed projects;
    otherwise it falls through to `clean_omnetpp` / `clean_project`.
    Clarify.

28. **doc/overlay_builds.md:133** —
    `from opp_repl.simulation.overlay import *` pulls in deprecated
    aliases (`OverlaySimulationProject`, `OverlayOmnetppProject`,
    `_collect_overlays_from_opp_files`, …). Probably not what users
    want; recommend explicit imports or add `__all__`.

29. **doc/task_results.md:40** — `SpeedUpdateTaskResult` row is
    duplicated under both Test and Update tables.

30. **doc/tasks.md:171-172** — "mode is forced to debug" happens in
    `get_simulation_tasks()` (`task.py:760-763`), not
    `SimulationTask.__init__`. Minor imprecision.

31. **doc/mcp_server.md** — Doesn't mention the hardcoded `port=9966`
    at FastMCP construction (`opp_repl/common/mcp.py:60`), which is
    overridden later via `_mcp.settings.port = port` at line 483.
    Verify override actually takes effect.

32. **doc/concepts.md:79-81** — Filter list claim is correct in effect
    (filters flow through `**kwargs`), but the signature of
    `get_simulation_tasks()` only directly declares `run_number_filter`
    and `exclude_run_number_filter`. Worth a clarifying note.

33. **doc/coverage.md:42** — Says ".profraw and merged profile are
    cleaned up automatically". True for the success path, but on
    `llvm-profdata` / `llvm-cov` failure, leftover files remain.

34. **doc/cluster.md:144-147** — `--nix-shell` is shown without
    mentioning the `-x` short alias (`opp_repl/main.py:49`).

## Nitpick

35. **README.md:31** — `opp_repl --load "opp/*.opp"` works only from the
    repo root. `--load @opp` (mentioned in
    `doc/getting_started.md:21`) is more robust for users following
    the README literally.

36. **doc/getting_started.md:38** — Example `Out[1]` list is not in
    sorted order, although `get_simulation_project_names()` returns
    sorted (`workspace.py:108-110`). Illustrative-only, but
    inconsistent.

37. **doc/overview.md:42-44** — Console banner version
    (`omnetpp-6.4.0`) is illustrative; harmless drift.

38. **doc/omnetpp_projects.md:78-91** — "Overlay builds" heading
    appears twice with awkward continuation.

39. **doc/github_actions.md:96** — Parameter table omits `**kwargs`
    for `dispatch_all_workflows()` even though `github.py:47`
    accepts them.

40. **`SimulationProject.__repr__`
    (`opp_repl/simulation/project.py:518-519`)** — Calls
    `repr(self, ["name", "version", "git_hash", "git_diff_hash"])`.
    The built-in `repr` only takes one argument; this would raise
    `TypeError`. Real code bug, surfaced by auditing the doc's
    `Out[2]: SimulationProject(...)` example.

## Top 7 to fix first

User-visible impact, in priority order:

1. `doc/running_simulations.md:54` — `get_fail_results` → `get_error_results`.
2. `doc/tasks.md:211-212` — `clean_simulation_results()` description
   contradicts code and contradicts `doc/running_simulations.md`.
3. `doc/cluster.md:91` — undefined
   `copy_binary_simulation_distribution_to_cluster`.
4. `doc/installation.md` — fix dependency count and reconcile with
   README's `pip install opp_repl`.
5. `doc/repl.md` — document `--mcp-token-hash`.
6. `doc/overview.md` — add missing 5–6 CLI tools.
7. `doc/opp_files.md` — complete the `SimulationProject` parameter table.

## Real code bugs surfaced

Not documentation issues, but found while verifying doc claims:

- `opp_repl/test/fingerprint/...`:
  `MultipleFingerprintTestTaskResults.__init` typo (should be `__init__`).
- `opp_repl/test/speed/...`:
  `MultipleSpeedUpdateTasks.run` returns the store rather than a
  `MultipleTaskResults`.
- `opp_repl/simulation/project.py:518-519`:
  `SimulationProject.__repr__` calls `repr(self, [...])` with two
  arguments — would raise `TypeError`.
- `opp_repl/main.py:86`:
  Calls `copy_binary_simulation_distribution_to_cluster` on a
  `SimulationProject`, but that method is not defined.
- `opp_repl/test/bisect.py:279-282, 330-333`:
  `bisect_smoke_tests` / `bisect_sanitizer_tests` accept
  `update_good_results=True` but never pass an
  `update_good_results_function`, so the flag is silently inert.
