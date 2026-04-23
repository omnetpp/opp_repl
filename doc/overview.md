# Overview

opp_repl is an interactive Python environment for OMNeT++ — run simulations,
analyze results, and automate testing from an IPython shell or the command
line.  See [Installation](installation.md) for setup and
[Getting started](getting_started.md) for a hands-on walkthrough.

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
