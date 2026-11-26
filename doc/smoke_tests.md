# Smoke Tests

Smoke tests are the most basic tests — they check if simulations run without
crashing and terminate properly.

A smoke test reads only the stdout and the stderr of the simulation, thus it
turns the result files and the eventlog off with
`--record-scalar-results=false --record-vector-results=false --record-eventlog=false`.
The simulation makes no `.sca`, `.vec` or `.elog` file, and the model runs as
before.  These options need OMNeT++ 6.2.0 or later.  A file that a module
writes itself, such as a PCAP file, is not a result file of OMNeT++ and is
written as before.

OMNeT++ removes an old file with the name of a result file at the start of
each run.  The test thus also gives the two result files another name with
`--output-scalar-file` and `--output-vector-file`, and the `.sca` and `.vec`
files of a manual run of the same config stay.  To get the result files of a simulation, use
`run_simulations`.

## The end of a run

A smoke test stops after 1 s of CPU time (`cpu_time_limit`). Where this limit
stops a run depends on the machine and on the build, so two runs of the same
test can stop at different events. A project can make the end deterministic
with a store of simulation-time limits in its `.opp` file:

```python
test_parameters={
    "smoke": {"defaults": {"run_number": 0}, "sim_time_limits": "tests/smoke/sim-time-limits.json"},
}
```

For each config, the store holds the simulation time that 1 s of CPU time
reaches on the CI machine. A smoke test of a config with a value stops at this
simulation time, and a CPU-time limit of 30 s only stops a run that does not get
there. A value of `null` means that the run ends by itself before 1 s of CPU
time. A config without a value stops after 1 s of CPU time, as without a store.
The sanitizer tests and the feature tests use the same store.

The deterministic end lets the change-based test selection record exactly what
a smoke test runs (see [Test map](test_map.md)).

`opp_update_smoke_test_sim_time_limits` runs the smoke tests with only the
CPU-time limit and writes the store. Run it on the CI machine, in the mode of the
smoke tests; with a filter, it changes only the values of the configs that it
runs:

```bash
opp_update_smoke_test_sim_time_limits -p inet -m debug
```

## Python API

```python
# Run smoke tests for all simulations from the default project
run_smoke_tests()

# Run for a specific project and config
run_smoke_tests(simulation_project=aloha_project,
                config_filter="PureAlohaExperiment")
```

Example output:

```
[6/7] . -c TandemQueueExperiment -r 3 PASS
[5/7] . -c TandemQueueExperiment -r 2 PASS
...
[2/7] . -c Fifo2 PASS
Multiple smoke test results: PASS, summary: 7 PASS in 0:00:01.117562
```

### Re-running tests

```python
r = run_smoke_tests(simulation_project=aloha_project,
                    config_filter="PureAlohaExperiment")

# Re-run all smoke tests from the last result
r = r.rerun()

# Re-run only the failed tests
r = r.get_fail_results().rerun()
```

## Command Line

```bash
opp_run_smoke_tests --load "/home/user/workspace/omnetpp/**/*.opp" -p fifo
```
