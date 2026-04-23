# Profiling

Profile simulation performance using Linux `perf` and visualize the
results with [Hotspot](https://github.com/KDAB/hotspot).  Uses the
`profile` build mode.

## Python API

```python
# Generate a perf.data profile and open it in Hotspot
open_profile_report(simulation_project=inet_project,
                    working_directory_filter="examples/ethernet",
                    config_filter="General",
                    run_number=0,
                    sim_time_limit="10s")

# Just generate the profile without opening it
report_file = generate_profile_report(
    simulation_project=inet_project,
    working_directory_filter="examples/ethernet",
    config_filter="General",
    run_number=0,
    sim_time_limit="10s")
```

Both functions run the simulation under `perf record -g --call-graph dwarf`
and write the output to `perf.data` in the simulation's working directory.
The `output_file` parameter can override the file name.
