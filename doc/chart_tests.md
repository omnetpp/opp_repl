# Chart Tests

Chart tests detect visual regressions in result analysis charts by
comparing rendered images against saved baseline images.  The baseline
is stored in the `media_folder` of the project.  Requires the `chart`
optional dependency group (matplotlib, numpy).

## Python API

```python
# Store baseline charts (first time, or after intentional changes)
update_chart_test_results(simulation_project=inet_project)

# Run tests — compares current charts against the baseline
run_chart_tests(simulation_project=inet_project)

# Filter by working directory
run_chart_tests(simulation_project=inet_project,
                working_directory_filter="showcases")
```

## Command Line

```bash
opp_update_chart_test_results --load "/home/user/workspace/inet/inet.opp" -p inet
opp_run_chart_tests --load "/home/user/workspace/inet/inet.opp" -p inet
```
