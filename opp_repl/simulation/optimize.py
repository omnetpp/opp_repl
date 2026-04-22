"""
Optimize simulation parameters to achieve desired result values.

This module uses ``scipy.optimize`` to find simulation parameter values that
minimize the difference between simulated results and desired target values.
Each evaluation runs the simulation as a subprocess, reads the result files,
and computes the absolute difference from the target.

The optimizer defaults to Nelder-Mead which is derivative-free and therefore
suitable for stochastic simulations where tiny parameter perturbations do not
change the output (same random seed).

See the *Parameter optimization* section in ``README.md`` for usage examples.
"""

import math
import sys
import time

import importlib.util
import numpy as np
import scipy.optimize

if importlib.util.find_spec('optimparallel'):
    import optimparallel

try:
    from omnetpp.scave.results import *
except ImportError:
    pass

from opp_repl.simulation.config import *
from opp_repl.simulation.task import *
from opp_repl.simulation.project import *

__sphinx_mock__ = True # ignore this module in documentation

def cost_function(parameter_values, simulation_task, expected_result_names, expected_result_values, fixed_parameter_names, fixed_parameter_values, fixed_parameter_assignments, fixed_parameter_units, parameter_names, parameter_assignments, parameter_units, kwargs, best):
    if any(math.isnan(v) or math.isinf(v) for v in parameter_values):
        print(f"  {parameter_names} = {list(parameter_values)}, skipping (invalid values)")
        return float('inf')
    all_parameter_assignments = [*fixed_parameter_assignments, *parameter_assignments]
    all_parameter_values = [*fixed_parameter_values, *parameter_values]
    all_parameter_units = [*fixed_parameter_units, *parameter_units]
    all_parameter_assignment_args = list(map(lambda name, value, unit: "--" + name + "=" + (unit.format(value) if "{" in unit else str(value) + unit), all_parameter_assignments, all_parameter_values, all_parameter_units))
    suffix = "-".join(map(str, all_parameter_values))
    output_scalar_file = "results/" + simulation_task.simulation_config.config + "-" + suffix + ".sca"
    output_vector_file = "results/" + simulation_task.simulation_config.config + "-" + suffix + ".vec"
    append_args = ["--output-scalar-file=" + output_scalar_file, "--output-vector-file=" + output_vector_file, *all_parameter_assignment_args]
    simulation_result = simulation_task.run(append_args=append_args, **kwargs)
    if simulation_result.result == "DONE":
        working_dir = simulation_task.simulation_config.working_directory
        project = simulation_task.simulation_config.simulation_project
        scalar_file = project.get_full_path(os.path.join(working_dir, output_scalar_file))
        vector_file = project.get_full_path(os.path.join(working_dir, output_vector_file))
        result_files = [f for f in [scalar_file, vector_file] if os.path.exists(f)]
        result_values = []
        for result_name in expected_result_names:
            filter_expression = f"name =~ {result_name}"
            value = math.nan
            for result_file in result_files:
                df = read_result_files(result_file, filter_expression=filter_expression, include_fields_as_scalars=True)
                scalars = df[df["type"] == "scalar"]
                if not scalars.empty:
                    value = float(scalars["value"].iloc[0])
                    break
                vectors = df[df["type"] == "vector"]
                if not vectors.empty:
                    value = float(vectors["vecvalue"].iloc[0][-1])
                    break
            result_values.append(value)
    else:
        print(f"  {parameter_names} = {list(parameter_values)}, simulation failed ({simulation_result.result})")
        return float('inf')
    result_value_absolute_differences = list(map(lambda x, y: abs(x - y), expected_result_values, result_values))
    cost = sum(result_value_absolute_differences)
    if cost < best["cost"]:
        best.update(cost=cost, parameter_values=list(parameter_values), result_values=result_values)
    print(f"  {parameter_names} = {parameter_values}, {expected_result_names} = {result_values}, diff = {result_value_absolute_differences}")
    return cost

def optimize_simulation_parameters(simulation_task, expected_result_names, expected_result_values,
                                   fixed_parameter_names, fixed_parameter_values, fixed_parameter_assignments, fixed_parameter_units,
                                   parameter_names, parameter_assignments, parameter_units,
                                   initial_values, min_values, max_values, tol=1E-3,
                                   method="Nelder-Mead", concurrent=False, simulation_runner=None, **kwargs):
    """
    Finds simulation parameter values that produce desired result values.

    Runs the simulation repeatedly with different parameter values, using
    ``scipy.optimize.minimize`` to search for the combination that minimizes
    the absolute difference between the simulated results and the targets.

    Parameters:
        simulation_task (SimulationTask):
            The simulation task to run.  Obtained from ``get_simulation_task()``.

        expected_result_names (list[str]):
            Names of the result scalars or vectors to match (e.g. ``["channelUtilization:last"]``).

        expected_result_values (list[float]):
            Target values for each result name.

        fixed_parameter_names (list[str]):
            Human-readable names for parameters that are held constant during optimization.

        fixed_parameter_values (list):
            Values for the fixed parameters.

        fixed_parameter_assignments (list[str]):
            INI-style parameter paths for the fixed parameters (e.g. ``["**.bitrate"]``).

        fixed_parameter_units (list[str]):
            Unit suffixes for the fixed parameters (e.g. ``["Mbps"]``).

        parameter_names (list[str]):
            Human-readable names for the parameters being optimized.

        parameter_assignments (list[str]):
            INI-style parameter paths for the optimized parameters
            (e.g. ``["Aloha.host[*].iaTime"]``).

        parameter_units (list[str]):
            Unit suffixes for the optimized parameters.  Plain strings like ``"s"``
            or ``"m"`` are appended directly to the value.  Format strings containing
            ``{0}`` (e.g. ``"exponential({0}s)"``) are formatted with the value, which
            is useful for wrapping values in distribution functions.

        initial_values (list[float]):
            Starting values for the optimized parameters.

        min_values (list[float]):
            Lower bounds for each optimized parameter.

        max_values (list[float]):
            Upper bounds for each optimized parameter.

        tol (float):
            Convergence tolerance passed to ``scipy.optimize.minimize``.

        method (str):
            Optimization method.  Defaults to ``"Nelder-Mead"`` which is derivative-free
            and suitable for stochastic simulations.

        concurrent (bool):
            If ``True``, uses ``optimparallel.minimize_parallel`` for parallel
            function evaluations (requires the ``optimparallel`` package).

    Returns (float or list[float]):
        The optimized parameter value (single parameter) or list of values
        (multiple parameters).
    """
    start_time = time.time()
    best = {"cost": float('inf'), "parameter_values": None, "result_values": None}
    xs = np.array(initial_values, dtype=float)
    bounds = list(map(lambda min, max: (min, max), min_values, max_values))
    args = (simulation_task, expected_result_names, expected_result_values, fixed_parameter_names, fixed_parameter_values, fixed_parameter_assignments, fixed_parameter_units, parameter_names, parameter_assignments, parameter_units, kwargs, best)
    if concurrent:
        result = optimparallel.minimize_parallel(cost_function, xs, args=args, bounds=bounds, tol=tol)
    else:
        result = scipy.optimize.minimize(cost_function, xs, args=args, bounds=bounds, tol=tol, method=method)
    end_time = time.time()
    elapsed_wall_time = end_time - start_time
    print(result)
    print(f"Best: {dict(zip(parameter_names, map(float, best['parameter_values'])))} -> {dict(zip(expected_result_names, map(float, best['result_values'])))}")
    print(f"Elapsed time: {elapsed_wall_time}")
    return float(result.x[0]) if len(result.x) == 1 else list(map(float, result.x))

