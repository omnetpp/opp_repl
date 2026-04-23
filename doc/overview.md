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

## Using Python Interactively

The simplest way to start using opp_repl in the interactive Python environment is to start the `opp_repl`
shell script. This script loads the `opp_repl.repl` Python module and launches an IPython interpreter.
Alternatively, it's also possible to use any other Python interpreter, and also to import the desired
individual opp_repl packages as needed.

After the installation is completed, starting the opp_repl interpreter from a terminal is pretty straightforward:

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

You can start typing in the prompt. For example, type `run` and press the TAB key to get completion options.
The Python interpreter provides completion options for module and package names, class and function names,
and method names and their parameters.

## Command-Line Options

```
opp_repl [-h]
         [-p PROJECT]              # set default simulation project by name
         [-l {ERROR,WARN,INFO,DEBUG}]  # log level (default: INFO)
         [--external-command-log-level {ERROR,WARN,INFO,DEBUG}]
         [--mcp-port PORT]         # MCP server port, 0 to disable (default: 0)
         [--load OPP_FILE]         # load .opp file(s), repeatable, supports globs
         [--handle-exception | --no-handle-exception]
```

## Command Line Tools

- `opp_repl` — starts the interactive Python interpreter
- `opp_build_project` — builds the simulation project
- `opp_run_simulations` — runs multiple simulations matching a filter criteria
- `opp_run_all_tests` — runs all tests matching a filter criteria
- `opp_run_chart_tests` — runs multiple chart tests matching a filter criteria
- `opp_run_feature_tests` — runs multiple feature tests matching a filter criteria
- `opp_run_fingerprint_tests` — runs multiple fingerprint tests matching a filter criteria
- `opp_run_release_tests` — runs multiple release tests matching a filter criteria
- `opp_run_sanitizer_tests` — runs multiple sanitizer tests matching a filter criteria
- `opp_run_smoke_tests` — runs multiple smoke tests matching a filter criteria
- `opp_run_speed_tests` — runs multiple speed tests matching a filter criteria
- `opp_run_statistical_tests` — runs multiple statistical tests matching a filter criteria
- `opp_update_charts` — updates baseline charts for chart tests
- `opp_update_correct_fingerprints` — updates stored correct fingerprints
- `opp_update_speed_results` — updates baseline speed measurements
- `opp_update_statistical_results` — updates baseline statistical results

All command line tools print a detailed description of their options when run with the `-h` option.

## REPL Features

### Autoreload

IPython's `%autoreload 2` magic is enabled at REPL startup so that
edited Python source files are automatically reloaded before each
command.

### User module

At startup the REPL tries to import a Python module named after the
current OS login user (e.g. `import levy`).  All public names from
that module are injected into the REPL namespace.  This allows
per-user customization — define helper functions, set project defaults,
etc. — without modifying opp_repl itself.  If no such module exists, the
import is silently skipped.

### Convenience variables

Every loaded simulation project is injected into the REPL namespace as
`{name}_project` (hyphens and dots replaced by underscores).  For
example, `inet_project`, `simu5g_project`, `aloha_project`.

### stop_execution()

Call `stop_execution()` (or `stop_execution(value)`) anywhere in a
REPL script to abort the current cell without a full traceback.
