# Parameter Optimization

Find simulation parameter values that produce desired results by iteratively
running simulations and minimizing the difference from a target.  Uses
`scipy.optimize` with Nelder-Mead (derivative-free, suitable for stochastic
simulations).  Requires the `optimize` extra (`scipy` and optionally
`optimparallel`).

## How it works

`optimize_simulation_parameters()` wraps `scipy.optimize.minimize` around the
simulation runner.  On each iteration:

1. The optimizer proposes new values for the optimized parameters.
2. The values are formatted into command-line overrides
   (e.g. `--Aloha.host[*].iaTime=exponential(1.5s)`).
3. The simulation task is run with these overrides; scalar and vector result
   files are written to a unique file per evaluation.
4. The target result names are read from the output files and the absolute
   difference from the expected values is computed as the cost.
5. The optimizer adjusts the parameters and repeats until convergence.

The default method is **Nelder-Mead**, which is derivative-free and works
well for stochastic simulations where small parameter perturbations may not
change the output (same random seed).

## Example 1 — Aloha channel utilization

Find the inter-arrival time that maximizes channel utilization in slotted ALOHA.
The theoretical maximum is 1/e ≈ 0.368; starting from the overloaded region (0.5 s)
the optimizer converges to iaTime ≈ 1.87 s in about 40 evaluations:

```python
optimize_simulation_parameters(
    get_simulation_task(config_filter="SlottedAloha1", sim_time_limit="10min"),
    expected_result_names=["channelUtilization:last"],
    expected_result_values=[0.368],
    fixed_parameter_names=[], fixed_parameter_values=[],
    fixed_parameter_assignments=[], fixed_parameter_units=[],
    parameter_names=["iaTime"],
    parameter_assignments=["Aloha.host[*].iaTime"],
    parameter_units=["exponential({0}s)"],
    initial_values=[0.5], min_values=[0.1], max_values=[20])
```

```
  ['iaTime'] = [0.5],  ['channelUtilization:last'] = [0.129], diff = [0.239]
  ['iaTime'] = [0.525], ['channelUtilization:last'] = [0.139], diff = [0.229]
  ...
  ['iaTime'] = [1.875], ['channelUtilization:last'] = [0.370], diff = [0.002]
  ...
Best: {'iaTime': 1.873} -> {'channelUtilization:last': 0.367}
Elapsed time: 1.13
```

Note: because `iaTime` is declared as `volatile` in NED with an
`exponential()` distribution in the INI file, the unit format
`"exponential({0}s)"` wraps the numeric value so that the command-line
override preserves the distribution.  Plain units like `"m"` or `"Mbps"`
are appended directly to the value.

## Example 2 — WiFi error rate distance (INET)

Find the distance at which 54 Mbps WiFi reaches a 30 % packet error rate.
The optimizer converges to ≈ 53.2 m in about 28 evaluations:

```python
optimize_simulation_parameters(
    get_simulation_task(simulation_project=inet_project,
        working_directory_filter="showcases/wireless/errorrate",
        config_filter="General", run_number=0, sim_time_limit="1s"),
    expected_result_names=["packetErrorRate:vector"],
    expected_result_values=[0.3],
    fixed_parameter_names=["bitrate"], fixed_parameter_values=[54],
    fixed_parameter_assignments=["**.bitrate"], fixed_parameter_units=["Mbps"],
    parameter_names=["distance"],
    parameter_assignments=["*.destinationHost.mobility.initialX"],
    parameter_units=["m"],
    initial_values=[50], min_values=[20], max_values=[100])
```

```
  ['distance'] = [50.0],  ['packetErrorRate:vector'] = [0.072], diff = [0.228]
  ['distance'] = [52.5],  ['packetErrorRate:vector'] = [0.226], diff = [0.074]
  ...
  ['distance'] = [53.19], ['packetErrorRate:vector'] = [0.300], diff = [0.000]
Best: {'distance': 53.194} -> {'packetErrorRate:vector': 0.300}
Elapsed time: 6.38
```

## Parameter reference

| Parameter | Description |
|---|---|
| `simulation_task` | A `SimulationTask` obtained from `get_simulation_task()` |
| `expected_result_names` | Result scalar/vector names to match (e.g. `["channelUtilization:last"]`) |
| `expected_result_values` | Target values, one per result name |
| `parameter_names` | Human-readable names for the optimized parameters |
| `parameter_assignments` | INI-style parameter paths (e.g. `["Aloha.host[*].iaTime"]`) |
| `parameter_units` | Unit suffixes or format strings (see below) |
| `initial_values` | Starting values for the optimizer |
| `min_values` / `max_values` | Bounds for each parameter |
| `fixed_parameter_names` | Names of parameters held constant during optimization |
| `fixed_parameter_values` | Values for the fixed parameters |
| `fixed_parameter_assignments` | INI-style paths for the fixed parameters |
| `fixed_parameter_units` | Unit suffixes for the fixed parameters |
| `tol` | Convergence tolerance (default `1e-3`) |
| `method` | `scipy.optimize` method (default `"Nelder-Mead"`) |
| `concurrent` | Use `optimparallel` for parallel evaluations (default `False`) |

## Units and distribution wrappers

The `parameter_units` list controls how numeric values are formatted into
command-line overrides:

- **Plain units** like `"s"`, `"m"`, `"Mbps"` are appended directly:
  value `1.5` with unit `"s"` → `1.5s`.
- **Format strings** containing `{0}` are used as templates:
  value `1.5` with unit `"exponential({0}s)"` → `exponential(1.5s)`.

The format-string form is needed when a NED parameter is declared as
`volatile` with a distribution function — the override must preserve
the distribution wrapper.

## Fixed parameters

Fixed parameters are passed to every simulation run but are not varied by
the optimizer.  This is useful when exploring a specific scenario (e.g.
a particular bitrate) while optimizing another parameter (e.g. distance).
Set all four `fixed_parameter_*` lists to empty lists `[]` when there
are no fixed parameters.

## Convergence and tolerance

The optimizer stops when further iterations improve the cost by less than
`tol` (default `1e-3`).  If the simulation fails during an evaluation
(non-zero exit code), the cost is reported as infinity and the optimizer
moves on.

Each evaluation prints a progress line showing the current parameter values,
result values, and per-result absolute differences.  At the end, the best
result found across all evaluations is printed.

## Parallel optimization

Set `concurrent=True` to use `optimparallel.minimize_parallel`, which
evaluates multiple parameter combinations simultaneously.  This requires
the `optimparallel` package and works best when each simulation is
relatively fast.

## Return value

`optimize_simulation_parameters()` returns the optimized parameter value
as a `float` (single parameter) or a `list[float]` (multiple parameters).
The full `scipy.optimize.OptimizeResult` is printed to stdout, including
convergence status and the number of function evaluations.
