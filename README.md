# opp_repl

An interactive Python REPL for OMNeT++ — run simulations, compare results,
optimize parameters, and run a wide range of regression tests.  Provides
an MCP server for AI assistants.  All features are accessible from both
the interactive REPL and command-line tools.  See the
[Overview](doc/overview.md) for the full feature list.

## Installation

Requires Python 3.10+.

```bash
pip install opp_repl
```

See [Installation](doc/installation.md) for details on optional extras
and environment setup.

## Quick Start

First, source the OMNeT++ environment:

```bash
. /path/to/omnetpp/setenv
```

Then launch the REPL using existing omnetpp installation:

```bash
opp_repl --load "etc/*.opp"
```

Then run simulations from the REPL:

```python
In [1]: run_simulations(simulation_project=fifo_project)
```

See [Getting started](doc/getting_started.md) for a full walkthrough.

## Documentation

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
