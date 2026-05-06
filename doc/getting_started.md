# Getting Started

This guide walks through the first steps with opp_repl — from launching
the REPL to running your first simulation.

## Starting the REPL

After [installation](installation.md), start the REPL and load one or more
`.opp` project descriptor files:

```bash
opp_repl --load ~/workspace/omnetpp/omnetpp.opp \
         --load "~/workspace/omnetpp/samples/*/*.opp"
```

The `--load` option accepts glob patterns, single files, or directories.
When a directory is given, all `*.opp` files in it are loaded.  Use the
special token `@opp` to load the bundled `.opp` files shipped with
opp_repl (useful for OMNeT++ sample projects):

```bash
opp_repl --load @opp
```

OMNeT++ projects are loaded first, then simulation projects, so
dependencies resolve automatically.

## Exploring loaded projects

Once inside the REPL every loaded project is available as a convenience
variable named `{name}_project`:

```python
In [1]: get_simulation_project_names()
Out[1]: ['aloha', 'fifo', 'tictoc', ...]

In [2]: aloha_project
Out[2]: SimulationProject(name='aloha', ...)
```

## Setting a default project

If you start the REPL from within a project directory, the default project
is detected automatically.  Otherwise set it explicitly:

```python
set_default_simulation_project(aloha_project)
```

Or use the `-p` command-line flag:

```bash
opp_repl --load "~/workspace/omnetpp/samples/*/*.opp" -p aloha
```

With a default project set, most functions can be called without specifying
a project.

## Running simulations

The quickest way to run simulations:

```python
run_simulations(sim_time_limit="1s")
```

This runs all non-abstract, non-emulation configs from the default project,
concurrently, with a one-second time limit.  Use filters to narrow the
selection:

```python
run_simulations(config_filter="PureAloha", sim_time_limit="1s")
```

The result object summarizes what happened and lets you drill down:

```python
r = run_simulations(config_filter="PureAloha", sim_time_limit="1s")
r.get_error_results()           # inspect failures
r.get_error_results().rerun()   # re-run only the failures
```

## Running tests

opp_repl supports several kinds of tests.  For example, smoke tests verify
that simulations start and terminate without crashing:

```python
run_smoke_tests(sim_time_limit="1s")
```

Fingerprint tests compare simulation behavior against a stored baseline:

```python
run_fingerprint_tests()
```

See the individual test guides for details on each test type.

## Using command-line tools

Every REPL function has a corresponding command-line tool.  For example:

```bash
opp_run_simulations --load aloha.opp --filter PureAloha -t 1s
opp_run_smoke_tests --load aloha.opp -t 1s
opp_run_fingerprint_tests --load inet.opp
```

When no `--load` option is given, the command-line tools automatically
load all `*.opp` files from the current working directory.  This means
you can `cd` into a project directory that contains `.opp` files and run
without extra arguments:

```bash
cd ~/workspace/omnetpp/samples/fifo
opp_run_simulations -t 1s
```

All tools accept `--help` for a full list of options.

## Next steps

- [Concepts](concepts.md) — understand the core abstractions
- [OPP files](opp_files.md) — learn how to write `.opp` project descriptors
- [Running simulations](running_simulations.md) — advanced simulation options
- [Fingerprint tests](fingerprint_tests.md) — regression testing
