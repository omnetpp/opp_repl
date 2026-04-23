# Overview

This page lists the full feature set, the interactive workflow, and the
available command-line tools.  See [Installation](installation.md) for setup
and [Getting started](getting_started.md) for a hands-on walkthrough.

## Features

- **Build projects** — build simulation binaries from Python
- **Run simulations** — run all or filtered simulations from a project,
  sequentially or concurrently, on localhost or an SSH cluster
- **Simulation comparison** — compare stdout trajectories, fingerprint trajectories, and scalar results between two projects or git commits
- **Parameter optimization** — find simulation parameter values that produce desired results using derivative-free optimization
- **Smoke tests** — verify that simulations start and terminate without crashing
- **Fingerprint tests** — detect behavioral regressions by comparing event fingerprints against a stored baseline
- **Statistical tests** — detect regressions in scalar results by comparing against stored baseline values
- **Speed tests** — detect performance regressions by comparing CPU instruction counts against a baseline
- **Chart tests** — detect visual regressions by comparing rendered analysis charts against baseline images
- **Sanitizer tests** — find memory errors and undefined behavior using AddressSanitizer / UBSan instrumentation
- **Feature tests** — verify that projects build and simulations set up correctly with different optional feature combinations
- **Release tests** — run a comprehensive validation suite for release builds
- **Test bisect** — find the git commit that introduced a test failure using binary search
- **Coverage reports** — generate C++ line-coverage reports using LLVM's coverage tools
- **Overlay builds** — out-of-tree builds using fuse-overlayfs on top of read-only source trees
- **SSH cluster execution** — distribute simulation tasks across multiple machines using Dask
- **GitHub Actions integration** — dispatch CI workflows from the REPL
- **IDE integration** — connect to the OMNeT++ IDE via Py4J
- **MCP server** — expose the REPL to AI assistants via the Model Context Protocol

## Using Python interactively

The `opp_repl` command launches an IPython interpreter with all simulation
functions pre-loaded.  You can also use any other Python interpreter and
import `opp_repl` directly.

A typical session:

```console
$ cd ~/workspace/omnetpp && . setenv
Environment for 'omnetpp-6.4.0' in directory '/home/user/workspace/omnetpp' is ready.
$ cd ~/workspace/opp_repl && . setenv
opp_repl is ready (added /home/user/workspace/opp_repl to PATH).
$ opp_repl --load ~/workspace/inet/inet.opp
INFO opp_repl.simulation.project Default project is set to inet
INFO opp_repl.repl OMNeT++ Python support is loaded.

In [1]:
```

Type `run` and press TAB for completion.  The interpreter completes module
names, function names, method names, and their parameters.

See [The REPL](repl.md) for details on REPL-specific features (autoreload,
convenience variables, user modules, etc.).

## Command-line tools

Many REPL functions have corresponding command-line tools:

- `opp_repl` — interactive Python interpreter
- `opp_build_project` — build a simulation project
- `opp_run_simulations` — run simulations matching a filter
- `opp_run_all_tests` — run all tests
- `opp_run_smoke_tests` — verify simulations start and terminate without crashing
- `opp_run_fingerprint_tests` — detect behavioral regressions via event fingerprints
- `opp_run_statistical_tests` — detect regressions in scalar results
- `opp_run_speed_tests` — detect performance regressions via CPU instruction counts
- `opp_run_chart_tests` — detect visual regressions in analysis charts
- `opp_run_sanitizer_tests` — find memory errors and undefined behavior
- `opp_run_feature_tests` — verify builds with different optional feature combinations
- `opp_run_release_tests` — run a comprehensive validation suite
- `opp_update_correct_fingerprints` — update the fingerprint baseline
- `opp_update_speed_results` — update the speed test baseline
- `opp_update_statistical_results` — update the statistical test baseline
- `opp_update_charts` — update the chart test baseline images

All tools print their options when run with `-h`.
