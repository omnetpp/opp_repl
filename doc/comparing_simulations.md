# Comparing Simulations

Compare simulation results between two projects or two git commits.
The comparison checks stdout trajectories, fingerprint trajectories,
and scalar statistical results.

## Python API

```python
# Compare two projects
results = compare_simulations(
    simulation_project_1=inet_project,
    simulation_project_2=inet_baseline_project,
    working_directory_filter="examples/ethernet",
    config_filter="General",
    run_number=0)

# Compare two git commits of the same project
results = compare_simulations_between_commits(
    inet_project, "HEAD~1", "HEAD",
    config_filter="General",
    run_number=0)

# Inspect the results
r = results.results[0]
print(r.stdout_trajectory_comparison_result)       # IDENTICAL / DIVERGENT
print(r.fingerprint_trajectory_comparison_result)   # IDENTICAL / DIVERGENT
print(r.statistical_comparison_result)              # IDENTICAL / DIFFERENT
r.print_different_statistical_results(include_relative_errors=True)

# Interactive debugging at the divergence point
r.debug_at_fingerprint_divergence_position()
r.show_divergence_position_in_sequence_chart()
```
