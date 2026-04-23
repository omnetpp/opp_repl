# Speed Tests

Speed tests detect performance regressions by measuring CPU instruction
counts and comparing them against stored baseline values.  Uses the
`profile` build mode and the `speed_store` JSON file.

## Python API

```python
# Store baseline measurements (first time, or after intentional changes)
update_speed_results(simulation_project=inet_project)

# Run tests — compares current measurements against the baseline
run_speed_tests(simulation_project=inet_project)

# Filter to specific simulations
run_speed_tests(simulation_project=inet_project,
                working_directory_filter="showcases")
```

## Command Line

```bash
opp_update_speed_results --load "/home/user/workspace/inet/inet.opp" -p inet
opp_run_speed_tests --load "/home/user/workspace/inet/inet.opp" -p inet
```
