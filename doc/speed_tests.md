# Speed Tests

Speed tests detect performance regressions by measuring CPU instruction
counts and comparing them against stored baseline values.  The project is
built in `profile` mode and the baseline is kept in the `speed_store` JSON
file configured via the project parameter.

## Prerequisites

Speed tests measure hardware CPU instruction counts using Linux performance
counters.  This requires:

- **Linux** — hardware performance counters are accessed via the
  `perf_event_open` system call, which is Linux-specific.
- **`perf_event_paranoid` sysctl** — the kernel must allow unprivileged access
  to performance counters.  Check the current setting with
  `cat /proc/sys/kernel/perf_event_paranoid`; a value of `1` or lower is
  needed.  To lower it temporarily: `sudo sysctl kernel.perf_event_paranoid=1`.
- **OMNeT++ `profile` build mode** — the project must be buildable in
  `profile` mode.  The `--measure-cpu-usage=true` simulation flag, which speed
  tests set automatically, enables the counter collection inside the OMNeT++
  runtime.

## Python API

### Storing baseline measurements

Before running speed tests a baseline must be established:

```python
update_speed_test_results(simulation_project=inet_project)
```

The update runs every matching simulation in `profile` mode at elevated
priority (`nice -10`) with all recording disabled, then stores the measured
values in the speed store.

### Running speed tests

```python
r = run_speed_tests(simulation_project=inet_project)

# Filter to specific simulations
run_speed_tests(simulation_project=inet_project,
                working_directory_filter="showcases")
```

### Understanding the test result

`run_speed_tests()` returns a `MultipleTestTaskResults` object.  Each element
in `r.results` is a `SimulationTestTaskResult` with:

- **`result`** — `"PASS"`, `"FAIL"`, `"SKIP"`, `"ERROR"`, or `"CANCEL"`
- **`reason`** — on `FAIL`, explains whether the instruction count was too large or too small relative to the baseline

A test **fails** when the relative difference between the measured and the
stored CPU instruction count exceeds the threshold (default 10 %):

```python
r0 = r.results[0]
print(r0.result)   # "PASS" or "FAIL"
print(r0.reason)   # e.g. "Number of CPU instructions is too large: 1234567 > 1000000"
```

Re-running and filtering works like other test types:

```python
r.get_fail_results().rerun()
```

### Understanding the update result

Each `SpeedUpdateTaskResult` carries:

- **`result`** — one of:
  - `"KEEP"` — the new measurement is within 10 % of the stored value
  - `"INSERT"` — no previous entry existed; a new baseline was stored
  - `"UPDATE"` — the stored value was replaced because the difference exceeded the threshold

### The speed measurement store

The speed store is a JSON file (path set by the `speed_store` project
parameter).  Each entry records:

- **`working_directory`**, **`ini_file`**, **`config`**, **`run_number`** — identify the simulation run
- **`sim_time_limit`** — the simulation time limit used
- **`elapsed_wall_time`** — wall-clock time of the measurement run
- **`elapsed_cpu_time`** — CPU time consumed
- **`num_cpu_cycles`** — hardware CPU cycle count
- **`num_cpu_instructions`** — hardware CPU instruction count (the primary metric)
- **`test_result`** — expected outcome (usually `"PASS"`)
- **`timestamp`** — when the entry was last written

You can query the store directly:

```python
store = get_speed_measurement_store(inet_project)

entry = store.find_entry(working_directory="examples/ethernet/lans",
                         config="General", run_number=0)

entries = store.filter_entries(config=None, run_number=None,
                               sim_time_limit=None)
```

After direct modifications, call `store.write()` to persist the changes.

## Command Line

```bash
opp_update_speed_test_results --load "/home/user/workspace/inet/inet.opp" -p inet
opp_run_speed_tests --load "/home/user/workspace/inet/inet.opp" -p inet
```
