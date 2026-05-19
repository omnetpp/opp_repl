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

Then launch the REPL using the bundled `.opp` descriptors for the
OMNeT++ sample projects:

```bash
opp_repl --load @opp
```

Each loaded project becomes a `{name}_project` variable — `fifo_project`,
`aloha_project`, etc.  Run simulations from the REPL:

```python
In [1]: run_simulations(simulation_project=fifo_project)
```

See [Getting started](doc/getting_started.md) for a full walkthrough.

## Documentation

### Start here

- [**Overview**](doc/overview.md) — features, CLI options, command-line tools
- [**Installation**](doc/installation.md) — requirements, install, optional extras, environment setup
- [**Getting started**](doc/getting_started.md) — first launch, running simulations, next steps
- [**The REPL**](doc/repl.md) — launch options, namespace, autoreload, user module

### Core model

- [**Concepts**](doc/concepts.md) — core concepts and how they fit together
- [**OPP files (`.opp`)**](doc/opp_files.md) — `.opp` file format, parameters, and examples
- [**Simulation workspaces**](doc/simulation_workspaces.md) — project registry, loading, lookup, defaults
- [**OMNeT++ projects**](doc/omnetpp_projects.md) — OMNeT++ installations, executables, building
- [**Simulation projects**](doc/simulation_projects.md) — model projects, source layout, dependencies, building
- [**Simulation configs**](doc/simulation_configs.md) — INI file discovery, filtering, run counts

### Running & inspecting

- [**Simulation tasks**](doc/tasks.md) — task creation, runners, build modes, re-running
- [**Task results**](doc/task_results.md) — result codes, inspection, filtering, re-running
- [**Running simulations**](doc/running_simulations.md) — running simulations, building projects, cleaning
- [**Building**](doc/building.md) — `build`/`mode`/`build_engine` parameters, recursive builds, artifact layout
- [**Comparing simulations**](doc/comparing_simulations.md) — simulation comparison

### Tests

- [**Smoke tests**](doc/smoke_tests.md) — smoke tests
- [**Fingerprint tests**](doc/fingerprint_tests.md) — fingerprint tests
- [**Statistical tests**](doc/statistical_tests.md) — statistical tests
- [**Comparison tests**](doc/comparison_tests.md) — regression detection via simulation comparison
- [**Speed tests**](doc/speed_tests.md) — speed tests
- [**Chart tests**](doc/chart_tests.md) — chart tests
- [**Sanitizer tests**](doc/sanitizer_tests.md) — sanitizer tests
- [**Feature tests**](doc/feature_tests.md) — feature tests, release tests, running all tests

### Advanced analysis

- [**Bisecting**](doc/bisecting.md) — bisecting git commits for test failures
- [**Parameter optimization**](doc/parameter_optimization.md) — parameter optimization
- [**Code coverage**](doc/coverage.md) — coverage reports
- [**Profiling**](doc/profiling.md) — performance profiling with perf and Hotspot

### Infrastructure

- [**Overlay builds**](doc/overlay_builds.md) — overlay builds
- [**Cluster**](doc/cluster.md) — SSH cluster execution
- [**GitHub Actions**](doc/github_actions.md) — GitHub Actions integration
- [**MCP server**](doc/mcp_server.md) — MCP server for AI assistants
