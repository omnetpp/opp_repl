# Fingerprint Tests

Fingerprint tests detect unintended behavioral changes by comparing a
hash of selected simulation state (trajectory, packet counts, etc.)
against stored baseline values.  The baseline is kept in a JSON store
file configured via the `fingerprint_store` project parameter.

## Python API

### Storing correct fingerprints

If there are no fingerprints in the store yet, they must be calculated and inserted first:

```python
update_fingerprint_test_results(simulation_project=inet_project, sim_time_limit="1s")
```

Example output:

```
[04/42] Updating fingerprint . -c PureAlohaExperiment -r 3 for 1s INSERT 856a-c13d/tplx
[11/42] Updating fingerprint . -c PureAlohaExperiment -r 10 for 1s INSERT 835c-d8e8/tplx
...
Multiple update fingerprint results: INSERT, summary: 42 INSERT (unexpected) in 0:00:01.567479
```

Updating fingerprints again when they haven't changed produces KEEP results:

```
Multiple update fingerprint results: KEEP, summary: 7 KEEP in 0:00:00.218112
```

### Running fingerprint tests

```python
r = run_fingerprint_tests(simulation_project=inet_project, sim_time_limit="1s")
```

Example output:

```
[02/42] Checking fingerprint . -c PureAlohaExperiment -r 1 for 1s PASS
...
Multiple fingerprint test results: PASS, summary: 42 PASS in 0:00:01.129969
```

PASS means the calculated fingerprint matches the stored value.

### Re-running and filtering

```python
# Re-run only the failures
r.get_fail_results().rerun()

# Filter to a specific area of the project
run_fingerprint_tests(simulation_project=inet_project,
                      working_directory_filter="examples/ethernet",
                      sim_time_limit="10s")

# Update fingerprints for a subset after intentional changes
update_fingerprint_test_results(simulation_project=inet_project,
                            working_directory_filter="examples/ethernet",
                            sim_time_limit="10s")
```

## Command Line

The typical workflow when starting from scratch:

```bash
# 1. Running tests without a baseline — all tests are skipped
opp_run_fingerprint_tests --load "/home/user/workspace/omnetpp/**/*.opp" -p fifo -t 1s
# Multiple fingerprint test results: SKIP, summary: 7 SKIP (unexpected) in 0:00:00.004558

# 2. Store correct fingerprints first
opp_update_fingerprint_test_results --load "/home/user/workspace/omnetpp/**/*.opp" -p fifo -t 1s
# [2/7] Updating fingerprint . -c Fifo2 for 1s INSERT 6593-438a/tplx
# ...
# Multiple update fingerprint results: INSERT, summary: 7 INSERT (unexpected) in 0:00:00.172821

# 3. Now tests pass
opp_run_fingerprint_tests --load "/home/user/workspace/omnetpp/**/*.opp" -p fifo -t 1s
# [3/7] Checking fingerprint . -c TandemQueueExperiment for 1s PASS
# ...
# Multiple fingerprint test results: PASS, summary: 7 PASS in 0:00:00.164720

# 4. Updating again when nothing changed — values are kept
opp_update_fingerprint_test_results --load "/home/user/workspace/omnetpp/**/*.opp" -p fifo -t 1s
# [5/7] Updating fingerprint . -c TandemQueueExperiment -r 2 for 1s KEEP 4cbd-3dae/tplx
# ...
# Multiple update fingerprint results: KEEP, summary: 7 KEEP in 0:00:00.218112
```
