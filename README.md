# opp_repl

An interactive Python REPL for OMNeT++ — run simulations, analyze results,
and automate testing from an IPython shell or the command line.

## Features

- **Run simulations** — run all or filtered simulations from a project,
  sequentially or concurrently, on localhost or an SSH cluster
- **MCP server** — expose the REPL to AI assistants via the Model Context Protocol
- **Build projects** — build simulation binaries from Python
- **Smoke tests** — verify that simulations start and terminate without crashing
- **Fingerprint tests** — detect behavioral regressions by comparing event fingerprints against a stored baseline
- **Statistical tests** — detect regressions in scalar results by comparing against stored baseline values
- **Chart tests** — detect visual regressions by comparing rendered analysis charts against baseline images
- **Speed tests** — detect performance regressions by comparing CPU instruction counts against a baseline
- **Feature tests** — verify that projects build and simulations set up correctly with different optional feature combinations
- **Sanitizer tests** — find memory errors and undefined behavior using AddressSanitizer / UBSan instrumentation
- **Release tests** — run a comprehensive validation suite for release builds
- **Parameter optimization** — find simulation parameter values that produce desired results using derivative-free optimization
- **Simulation comparison** — compare stdout trajectories, fingerprint trajectories, and scalar results between two projects or git commits
- **Coverage reports** — generate C++ line-coverage reports using LLVM's coverage tools
- **Overlay builds** — out-of-tree builds using fuse-overlayfs on top of read-only source trees
- **SSH cluster execution** — distribute simulation tasks across multiple machines using Dask
- **GitHub Actions integration** — dispatch CI workflows from the REPL
- **IDE integration** — connect to the OMNeT++ IDE via Py4J

All features are accessible both from the interactive REPL and as
command-line tools (`opp_run_simulations`, `opp_run_fingerprint_tests`,
`opp_update_correct_fingerprints`, etc.).

## Installation

Requires Python 3.10+.

```bash
pip install -e .
```

Optional extras:

```bash
pip install -e ".[all]"     # install every optional group
pip install -e ".[cluster]" # just one group
```

| Extra | Packages | Purpose |
|---|---|---|
| `cluster` | dask, distributed | SSH cluster execution via Dask |
| `chart` | matplotlib, numpy | Chart tests and image export |
| `mcp` | mcp | MCP server for AI assistant integration |
| `optimize` | scipy, optimparallel | Parameter optimization |
| `github` | requests | GitHub API integration |
| `ide` | py4j | OMNeT++ IDE integration |
| `all` | *(all of the above)* | Everything |

## Quick Start

```bash
# Start the REPL, loading project descriptors
opp_repl --load ~/workspace/omnetpp/omnetpp.opp \
         --load "~/workspace/omnetpp/samples/*/*.opp"

# Or load opp_env-managed projects
opp_repl --load "~/opp_env/**/*.opp"

# Multiple --load arguments can be combined
opp_repl --load ~/workspace/omnetpp/omnetpp.opp \
         --load "~/workspace/omnetpp/samples/*/*.opp" \
         --load ~/workspace/inet/inet.opp
```

Once inside the REPL:

```python
In [1]: run_simulations(simulation_project=fifo_project)
```

## Documentation

Detailed guides are in the [`doc/`](doc/) folder:

- [**overview**](doc/overview.md) — features, installation, CLI options, REPL features, command-line tools
- [**concepts**](doc/concepts.md) — core concepts (OmnetppProject, SimulationProject, configs, tasks, filtering, etc.)
- [**opp_files**](doc/opp_files.md) — `.opp` file format, parameters, and example files
- [**running_simulations**](doc/running_simulations.md) — running simulations, building projects, loading, cleaning
- [**smoke_tests**](doc/smoke_tests.md) — smoke tests
- [**fingerprint_tests**](doc/fingerprint_tests.md) — fingerprint tests
- [**statistical_tests**](doc/statistical_tests.md) — statistical tests
- [**chart_tests**](doc/chart_tests.md) — chart tests
- [**speed_tests**](doc/speed_tests.md) — speed tests
- [**sanitizer_tests**](doc/sanitizer_tests.md) — sanitizer tests
- [**feature_tests**](doc/feature_tests.md) — feature tests, release tests, running all tests
- [**coverage**](doc/coverage.md) — coverage reports
- [**optimization**](doc/optimization.md) — parameter optimization
- [**comparing_simulations**](doc/comparing_simulations.md) — simulation comparison
- [**overlay_builds**](doc/overlay_builds.md) — overlay builds
- [**cluster**](doc/cluster.md) — SSH cluster execution
- [**github_actions**](doc/github_actions.md) — GitHub Actions integration
- [**mcp_server**](doc/mcp_server.md) — MCP server for AI assistants

## License

See the project repository for license information.
