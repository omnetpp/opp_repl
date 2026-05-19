# Installation

## Requirements

opp_repl requires **Python 3.10** or later.  It runs on Linux and macOS.

## Basic install

The released version is available from PyPI:

```bash
pip install opp_repl
```

For development or to track the latest changes, clone the repository
and install in editable mode instead:

```bash
git clone https://github.com/omnetpp/opp_repl.git
cd opp_repl
pip install -e .
```

Either form pulls in the only mandatory dependency — **IPython** (for
the interactive shell).

## Optional extras

Several features require additional packages.  Install them individually
or all at once:

```bash
pip install -e ".[all]"       # everything
pip install -e ".[cluster]"   # just one group
```

| Extra | Packages | Purpose |
|---|---|---|
| `mcp` | mcp | MCP server for AI assistant integration |
| `data` | pandas | DataFrame-based inspection of simulation/test results |
| `optimize` | scipy, optimparallel | Parameter optimization |
| `chart` | matplotlib, numpy | Chart tests and image export |
| `cluster` | dask, distributed | SSH cluster execution via Dask |
| `github` | requests | GitHub API integration |
| `ide` | py4j | OMNeT++ IDE integration |
| `all` | *(all of the above)* | Everything |

## Setting up the environment

Before starting opp_repl you typically need OMNeT++ on the path.  Source
its `setenv` script, then source the opp_repl one:

```bash
cd ~/workspace/omnetpp && . setenv
cd ~/workspace/opp_repl && . setenv
```

After this, the `opp_repl` command and all `opp_*` command-line tools are
available.

## Verifying the installation

```bash
opp_repl --help
```

If this prints the usage message, the installation is working.
