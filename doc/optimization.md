# Parameter Optimization

Find simulation parameter values that produce desired results by iteratively
running simulations and minimizing the difference from a target.  Uses
`scipy.optimize` with Nelder-Mead (derivative-free, suitable for stochastic
simulations).  Requires the `optimize` extra.

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
