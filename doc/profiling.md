# Profiling

Profile simulation performance using Linux `perf` and visualize the
results with [Hotspot](https://github.com/KDAB/hotspot).  Uses the
`profile` build mode.

## Prerequisites

Profiling requires:

- **Linux `perf` tool** — the `perf record` command must be available on
  `PATH`.  On Debian/Ubuntu, install it with
  `sudo apt install linux-tools-common linux-tools-$(uname -r)`.
- **`perf_event_paranoid` sysctl** — the kernel must allow `perf record`.
  Check with `cat /proc/sys/kernel/perf_event_paranoid`; a value of `1` or
  lower is needed.  To lower it temporarily:
  `sudo sysctl kernel.perf_event_paranoid=1`.
- **[Hotspot](https://github.com/KDAB/hotspot)** *(optional)* — required only
  by `open_profile_report()` to visualize the profile interactively.  Without
  it you can still use `generate_profile_report()` to produce the `perf.data`
  file and analyze it with other tools.
- **OMNeT++ `profile` build mode** — the project is automatically built in
  `profile` mode, which compiles with debug symbols and optimization enabled.

No extra Python packages are required.

## How it works

Both `generate_profile_report()` and `open_profile_report()` follow the same
pipeline:

1. The simulation project is built in `profile` mode (optimized with debug
   symbols).
2. The simulation is run under `perf record -g --call-graph dwarf`, which
   collects a hardware-level call-graph profile.
3. The output is written to `perf.data` (or a custom name via the
   `output_file` parameter) in the simulation's working directory.
4. `open_profile_report()` additionally launches
   [Hotspot](https://github.com/KDAB/hotspot) to visualize the profile
   interactively.

The functions accept all the same filter parameters as `run_simulations()`
(e.g. `working_directory_filter`, `config_filter`, `run_number`,
`sim_time_limit`).

## Python API

### Generating and visualizing a profile

```python
# Generate a perf.data profile and open it in Hotspot
open_profile_report(simulation_project=inet_project,
                    working_directory_filter="examples/ethernet",
                    config_filter="General",
                    run_number=0,
                    sim_time_limit="10s")
```

### Generating a profile without visualization

```python
report_file = generate_profile_report(
    simulation_project=inet_project,
    working_directory_filter="examples/ethernet",
    config_filter="General",
    run_number=0,
    sim_time_limit="10s")

# report_file is a project-relative path, e.g. "examples/ethernet/lans/perf.data"
```

The returned path can be analyzed with any `perf`-compatible tool:

```bash
perf report -i examples/ethernet/lans/perf.data
```

### Parameters

Both functions accept:

- **`simulation_project`** — the simulation project (defaults to the current
  default project)
- **`output_file`** — file name for the `perf.data` output (default
  `"perf.data"`)
- All filter parameters from `run_simulations()`: `working_directory_filter`,
  `config_filter`, `run_number`, `sim_time_limit`, etc.

## Command Line

There are no dedicated command-line wrappers for profiling.  Use the Python
API from within `opp_repl`.
