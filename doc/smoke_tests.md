# Smoke Tests

Smoke tests are the most basic tests — they check if simulations run without
crashing and terminate properly.

A smoke test reads only the stdout and the stderr of the simulation, thus it
turns the result files and the eventlog off with
`--record-scalar-results=false --record-vector-results=false --record-eventlog=false`.
The simulation makes no `.sca`, `.vec` or `.elog` file, and the model runs as
before.  These options need OMNeT++ 6.2.0 or later.  A file that a module
writes itself, such as a PCAP file, is not a result file of OMNeT++ and is
written as before.  To get the result files of a simulation, use
`run_simulations`.

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
