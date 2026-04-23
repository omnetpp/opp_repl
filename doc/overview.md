# Overview

opp_repl is an interactive Python environment for OMNeT++ — run simulations,
analyze results, and automate testing from an IPython shell or the command
line.  See [Installation](installation.md) for setup and
[Getting started](getting_started.md) for a hands-on walkthrough.

## Features

- **Run simulations** — run all or filtered simulations from a project,
  sequentially or concurrently, on localhost or an SSH cluster
- **Build projects** — build simulation binaries from Python
- **Simulation comparison** — compare stdout trajectories, fingerprint trajectories, and scalar results between two projects or git commits
- **Parameter optimization** — find simulation parameter values that produce desired results using derivative-free optimization
- **Smoke tests** — verify that simulations start and terminate without crashing
- **Fingerprint tests** — detect behavioral regressions by comparing event fingerprints against a stored baseline
- **Statistical tests** — detect regressions in scalar results by comparing against stored baseline values
- **Chart tests** — detect visual regressions by comparing rendered analysis charts against baseline images
- **Speed tests** — detect performance regressions by comparing CPU instruction counts against a baseline
- **Feature tests** — verify that projects build and simulations set up correctly with different optional feature combinations
- **Sanitizer tests** — find memory errors and undefined behavior using AddressSanitizer / UBSan instrumentation
- **Release tests** — run a comprehensive validation suite for release builds
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

Every REPL function has a corresponding command-line tool:

- `opp_repl` — interactive Python interpreter
- `opp_build_project` — build a simulation project
- `opp_run_simulations` — run simulations matching a filter
- `opp_run_all_tests` — run all tests
- `opp_run_smoke_tests`, `opp_run_fingerprint_tests`, `opp_run_statistical_tests`, `opp_run_speed_tests`, `opp_run_chart_tests`, `opp_run_sanitizer_tests`, `opp_run_feature_tests`, `opp_run_release_tests` — run specific test types
- `opp_update_correct_fingerprints`, `opp_update_speed_results`, `opp_update_statistical_results`, `opp_update_charts` — update baselines

All tools print their options when run with `-h`.
