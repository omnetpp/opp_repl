# Building

How opp_repl builds OMNeT++ and simulation projects. Three orthogonal
parameters control building (`build`, `mode`, `build_mode`); the names
are easy to confuse, so this guide starts with a side-by-side table.

## Three orthogonal parameters

| Parameter    | What it controls                                | Typical values                                                          |
|--------------|-------------------------------------------------|-------------------------------------------------------------------------|
| `build`      | *Whether* to build before running               | `True` / `False` (default: `get_default_build_argument()`)              |
| `mode`       | *Which kind of binary* to build/run             | `release`, `debug`, `sanitize`, `coverage`, `profile`                   |
| `build_mode` | *How* the build is driven                       | `makefile`, `task` (default: `get_default_build_mode()` → `makefile`)   |

The collision is unfortunate — `build_mode` reads like "build/debug/release mode"
but really means "build engine". `mode` is the artifact flavor.

```python
# Build a debug binary using the makefile engine, then run it:
build_project(simulation_project=p, mode="debug", build_mode="makefile")
run_simulations(simulation_project=p, mode="debug")

# Skip the implicit build before running (use whatever binary is on disk):
run_simulations(simulation_project=p, mode="debug", build=False)
```

## What gets built when

Running simulations is the common entry point and builds implicitly:

```python
run_simulations(simulation_project=p)         # builds (release), then runs
run_simulations(simulation_project=p, mode="debug")   # builds debug, runs debug
run_simulations(simulation_project=p, build=False)    # uses existing binary as-is
```

Tests and updates build implicitly too, defaulting to **debug** mode (assertions
on, better stack traces — see "Per-wrapper mode defaults" below):

```python
run_smoke_tests()                # builds debug, runs smoke tests
run_statistical_tests()          # builds debug, runs statistical tests
run_fingerprint_tests()          # builds debug, runs fingerprint tests
run_feature_tests()              # builds debug as a baseline,
                                 #   then per-feature toggles rebuild as needed
update_fingerprint_test_results()  # builds debug, then updates stored fingerprints
update_statistical_test_results()  # builds debug, then updates stored stats
```

To trigger a build without running anything, call `build_project` or
`SimulationProject.build`:

```python
build_project(simulation_project=p)               # release, current project only
build_project(simulation_project=p, mode="debug") # debug, current project only
p.build()                                         # release, recursive (see below)
p.build(mode="debug")                             # debug, recursive
```

`build_project` is the **non-recursive primitive** — it builds just the named
project. `SimulationProject.build` is **recursive** by default — it builds
OMNeT++ first, then any `used_projects`, then the project itself. Use
`recursive=False` to override.

To skip an implicit build, pass `build=False` to any entry point that supports
it (`run_simulations`, `run_*_tests`, `update_*_test_results`).

## Build modes (artifact flavors)

The `mode` parameter selects which kind of binary to build and run:

| Mode       | Binary suffix | Purpose                                                                |
|------------|---------------|------------------------------------------------------------------------|
| `release`  | `_release`    | Optimized build. Default for `run_simulations`, `compare_simulations`. |
| `debug`    | `_dbg`        | Assertions on, no optimization. Default for all test/update wrappers.  |
| `sanitize` | `_sanitize`   | Built with `-fsanitize=address,undefined`. Used by `run_sanitizer_tests`. |
| `coverage` | `_coverage`   | Built with `-fprofile-instr-generate -fcoverage-mapping`. Used by `generate_coverage_report`. |
| `profile`  | `_profile`    | Built with `-fno-omit-frame-pointer` for `perf record`. Used by `generate_profile_report` and `run_speed_tests`. |

`SimulationProject.get_executable(mode=...)` returns the path to the binary
with the right suffix. `OmnetppProject.get_library_suffix(mode)` is the
canonical lookup.

### Per-wrapper mode defaults

| Wrapper / function                                  | Default `mode` |
|-----------------------------------------------------|----------------|
| `SimulationTask`, `MultipleSimulationTasks`         | `release`      |
| `get_simulation_tasks` (resolves `None`)            | `release`, or `debug` if `debug=True` / breakpoints set |
| `MultipleSimulationTestTasks` and all test/update wrappers | `debug` |
| `get_sanitizer_test_tasks`                          | `sanitize`     |
| `get_speed_test_tasks`, `generate_profile_report`   | `profile`      |
| `generate_coverage_report`                          | `coverage`     |

The "test/update wrappers default to debug" choice is intentional: tests are
more useful with assertions enabled, and crashes produce readable stack
traces. An explicit `mode=...` argument always wins over the default.

### Mode/build-mode invariant

Per-task `mode` and wrapper-level `mode` are always equal. The entry points
(`get_simulation_test_tasks`, `get_update_*_tasks`, …) set the `mode` default
once and forward the same value to both the inner `SimulationTask` objects
and the wrapper, so `build_before_run` and the launched executable cannot
disagree.

## Build engines

The `build_mode` parameter selects how the build is driven. It is orthogonal
to `mode` — any `mode` works with either engine.

| `build_mode` | Engine                                                                  |
|--------------|-------------------------------------------------------------------------|
| `makefile`   | Runs `make MODE=<mode>` against the Makefile that `opp_makemake` produces. |
| `task`       | Drives the build through per-file `MsgCompileTask`, `CppCompileTask`, `LinkTask`, and `CopyBinaryTask`. |

`makefile` is the default and matches what you get on the command line.
`task` is useful when you want finer-grained progress reporting or per-file
result caching. Switch the global default with `set_default_build_mode`:

```python
from opp_repl.simulation.build import set_default_build_mode
set_default_build_mode("task")
```

## Recursive builds

`SimulationProject.build(recursive=True)` walks the dependency graph:

1. If the project has `used_projects`, each used project is built recursively
   (which in turn pulls in *its* used projects and OMNeT++).
2. Otherwise, the project's OMNeT++ installation is built directly via
   `OmnetppProject.build`.
3. The project itself is built via `build_project`.

Step 2 only runs when `used_projects` is empty — when a project has used
projects, the direct OMNeT++ build is reached transitively through them.

Pass `recursive=False` to build only the named project:

```python
p.build(recursive=False)   # just this project, assume deps are already built
```

## Cleaning

`clean_project` and `SimulationProject.clean` mirror `build_project` and
`SimulationProject.build` exactly — same `mode` and `build_mode` axes:

```python
clean_project(simulation_project=p, mode="debug")   # removes debug artifacts
p.clean(mode="debug")                                # recursive debug clean
```

`mode="debug"` cleans only the `_dbg`-suffixed binaries and the
`out/clang-debug/` (or `out/<config>/`) output folder for that mode — release
binaries built earlier survive. Use `task` build_mode to clean via opp_repl's
own clean tasks; `makefile` build_mode dispatches to `make clean MODE=<mode>`.

## Build artifacts on disk

For a simulation project at `/path/to/proj`:

| Path                                | Contents                                                       |
|-------------------------------------|----------------------------------------------------------------|
| `out/clang-<mode>/`                 | Per-file object files and intermediate outputs.                |
| `out/<makefile_inc.configname>/`    | Same, when the project has a `Makefile.inc` with a configname. |
| `bin/<executable><suffix>`          | Copied executable, e.g. `bin/runner_dbg`.                      |
| `lib/lib<library><suffix>.so`       | Copied dynamic library, e.g. `lib/libinet_dbg.so`.             |

`<suffix>` is `""` for release, `_dbg` for debug, `_sanitize`, `_coverage`,
`_profile` for the corresponding modes (or the project's
`makefile_inc.debug_suffix` when a `Makefile.inc` is available).

`SimulationProject.get_executable(mode=...)` returns the absolute path of the
copied executable for the given mode. For OMNeT++ itself the path is
`bin/opp_run<suffix>` under the OMNeT++ root.

## Overlay builds

Use `overlay_name` on a project to build into an overlayfs layer on top of a
read-only source tree. See [Overlay builds](overlay_builds.md).

## opp_env workspaces

Setting `opp_env_workspace` and `opp_env_project` on a project reroutes
`build` / `clean` / `run` through `opp_env`, so the build runs inside the
opp_env-managed environment and the binary is invoked the same way. The same
`mode` / `build_mode` rules apply.

## Config discovery and mode

`SimulationProject.get_simulation_configs` discovers configs by invoking
`opp_run … -q numruns`. It uses the **same mode as the caller**: when
invoked from `run_simulations(mode="debug")` or `run_smoke_tests(...)`,
discovery runs against the debug build. Called bare
(`inet_project.get_simulation_configs()`), the default is `"release"`.

The implicit pre-discovery build also uses the inherited mode, so
calling `run_simulations(mode="debug")` on a project that has never
been built triggers a single debug build that covers both config
discovery and the actual run.
