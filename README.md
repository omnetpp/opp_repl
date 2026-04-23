# opp_repl

An interactive Python REPL for OMNeT++ — run simulations, analyze results,
and automate testing from an IPython shell or the command line.

## Features

- **Run simulations** — run all or filtered simulations from a project,
  sequentially or concurrently, on localhost or an SSH cluster
- **MCP server** — expose the REPL to AI assistants via the Model Context Protocol
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
- **Build projects** — build simulation binaries from Python

All features are accessible both from the interactive REPL and as
command-line tools (`opp_run_simulations`, `opp_run_fingerprint_tests`,
`opp_update_correct_fingerprints`, etc.).

## Installation

Requires Python 3.10+.

```bash
pip install -e .
pip install -e ".[all]"   # optional: install all extras
```

See [Installation](doc/installation.md) for details on optional extras
and environment setup.

## Quick Start

```bash
opp_repl --load ~/workspace/omnetpp/omnetpp.opp \
         --load "~/workspace/omnetpp/samples/*/*.opp"
```

```python
In [1]: run_simulations(simulation_project=fifo_project)
```

See [Getting started](doc/getting_started.md) for a full walkthrough.

## Documentation

Detailed guides are in the [`doc/`](doc/) folder:

- [**Overview**](doc/overview.md) — features, CLI options, command-line tools
- [**Installation**](doc/installation.md) — requirements, install, optional extras, environment setup
- [**Getting started**](doc/getting_started.md) — first launch, running simulations, next steps
- [**The REPL**](doc/repl.md) — launch options, namespace, autoreload, user module
- [**Concepts**](doc/concepts.md) — core concepts and how they fit together
- [**OPP files**](doc/opp_files.md) — `.opp` file format, parameters, and examples
- [**Simulation workspaces**](doc/simulation_workspaces.md) — project registry, loading, lookup, defaults
- [**OMNeT++ projects**](doc/omnetpp_projects.md) — OMNeT++ installations, executables, building
- [**Simulation projects**](doc/simulation_projects.md) — model projects, source layout, dependencies, building
- [**Simulation configs**](doc/simulation_configs.md) — INI file discovery, filtering, run counts
- [**Simulation tasks**](doc/tasks.md) — task creation, runners, build modes, re-running
- [**Task results**](doc/task_results.md) — result codes, inspection, filtering, re-running
- [**Running simulations**](doc/running_simulations.md) — running simulations, building projects, cleaning
- [**Comparing simulations**](doc/comparing_simulations.md) — simulation comparison
- [**Smoke tests**](doc/smoke_tests.md) — smoke tests
- [**Fingerprint tests**](doc/fingerprint_tests.md) — fingerprint tests
- [**Statistical tests**](doc/statistical_tests.md) — statistical tests
- [**Speed tests**](doc/speed_tests.md) — speed tests
- [**Chart tests**](doc/chart_tests.md) — chart tests
- [**Sanitizer tests**](doc/sanitizer_tests.md) — sanitizer tests
- [**Feature tests**](doc/feature_tests.md) — feature tests, release tests, running all tests
- [**Parameter optimization**](doc/parameter_optimization.md) — parameter optimization
- [**Code coverage**](doc/coverage.md) — coverage reports
- [**Profiling**](doc/profiling.md) — performance profiling with perf and Hotspot
- [**Overlay builds**](doc/overlay_builds.md) — overlay builds
- [**Cluster**](doc/cluster.md) — SSH cluster execution
- [**GitHub Actions**](doc/github_actions.md) — GitHub Actions integration
- [**MCP server**](doc/mcp_server.md) — MCP server for AI assistants

## License

See [LICENSE](LICENSE).
