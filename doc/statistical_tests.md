# Statistical Tests

Statistical tests detect regressions in simulation scalar results by
comparing them against saved baseline values.  The baseline is stored
in the `statistics_folder` of the simulation project.

## Python API

```python
# Store baseline results (first time, or after intentional changes)
update_statistical_test_results(simulation_project=inet_project)

# Run tests — compares current results against the baseline
run_statistical_tests(simulation_project=inet_project)

# Filter to a specific area
run_statistical_tests(simulation_project=inet_project,
                      working_directory_filter="examples/ethernet")
```

## Command Line

```bash
opp_update_statistical_test_results --load "/home/user/workspace/inet/inet.opp" -p inet
opp_run_statistical_tests --load "/home/user/workspace/inet/inet.opp" -p inet
```
