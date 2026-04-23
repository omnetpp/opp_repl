# Smoke Tests

Smoke tests are the most basic tests — they check if simulations run without
crashing and terminate properly.

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
r = r.get_failed_results().rerun()
```

## Command Line

```bash
opp_run_smoke_tests --load "/home/user/workspace/omnetpp/**/*.opp" -p fifo
```
