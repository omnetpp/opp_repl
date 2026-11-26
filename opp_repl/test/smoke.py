"""
This module provides functionality for smoke testing of multiple simulations.

The main function is :py:func:`run_smoke_tests`. It allows running multiple smoke tests matching the
provided filter criteria. Smoke tests check if simulations run without crashing and terminate properly.

A smoke test stops after 1 s of CPU time, so how far it gets depends on the machine. A project can
give a store of simulation-time limits, ``test_parameters["smoke"]["sim_time_limits"]`` in its
``.opp`` file: for each config, the simulation time that 1 s of CPU time reaches on the CI machine.
With a value, the smoke test, the sanitizer test and the feature test of the config stop at this
simulation time, so their end is deterministic, and the larger CPU-time limit
:py:data:`SMOKE_TEST_SAFETY_CPU_TIME_LIMIT` only stops a run that does not get there. A value of
``null`` means that the run ends before 1 s of CPU time by itself. A config without a value keeps the
CPU-time limit. :py:func:`update_smoke_test_sim_time_limits` writes the store. See decision D2 of the
test selection plan of opp_repl (``plan/pending/test-selection.md``, section 7).
"""

import json
import re
import logging
import os

from opp_repl.simulation import *
from opp_repl.test.simulation import *

_logger = logging.getLogger(__name__)

class SmokeTestTask(SimulationTestTask):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def run_protected(self, append_args=[], **kwargs):
        return super().run_protected(append_args=no_result_files_append_args + append_args, **kwargs)

    def check_simulation_task_result(self, simulation_task_result, **kwargs):
        # TODO check simulation_task_result.elapsed_cpu_time
        return super().check_simulation_task_result(simulation_task_result, **kwargs)

# the CPU-time limit of a run whose config has a simulation-time limit in the store: a safety stop
SMOKE_TEST_SAFETY_CPU_TIME_LIMIT = "30s"

def get_smoke_test_sim_time_limits_file(simulation_project):
    """Returns the path of the store of the simulation-time limits of the smoke tests of the project, or None if the project has no store."""
    store = simulation_project.test_parameters.get("smoke", {}).get("sim_time_limits")
    return simulation_project.get_full_path(store) if store else None

def _get_sim_time_limit_key(working_directory, ini_file, config, run_number):
    return (working_directory, ini_file, config, run_number)

def read_smoke_test_sim_time_limits(simulation_project):
    """
    Returns the store of the simulation-time limits of the project as ``{(working directory, ini file,
    config, run number): limit}``; a limit is a string such as ``"0.4s"``, or None for a run that ends
    by itself. Returns None if the project has no store.
    """
    file_name = get_smoke_test_sim_time_limits_file(simulation_project)
    if not file_name:
        return None
    if not os.path.exists(file_name):
        _logger.warning(f"The store of the simulation-time limits {file_name} does not exist, so the smoke tests stop after their CPU-time limit")
        return {}
    with open(file_name) as f:
        entries = json.load(f)
    return {_get_sim_time_limit_key(entry["working_directory"], entry["ini_file"], entry["config"], entry["run_number"]): entry["sim_time_limit"] for entry in entries}

def get_smoke_test_time_limits(simulation_project, cpu_time_limit="1s", sim_time_limits=None, safety_cpu_time_limit=SMOKE_TEST_SAFETY_CPU_TIME_LIMIT):
    """
    Returns the ``(sim_time_limit, cpu_time_limit)`` of the tasks of the smoke, sanitizer and
    feature tests: functions of the config and the run number if the project has a store of
    simulation-time limits (see the module documentation), else ``(None, cpu_time_limit)``.
    *sim_time_limits* replaces the store of the project.
    """
    limits = sim_time_limits if sim_time_limits is not None else read_smoke_test_sim_time_limits(simulation_project)
    if limits is None:
        return None, cpu_time_limit
    def get_key(simulation_config, run_number):
        return _get_sim_time_limit_key(simulation_config.working_directory, simulation_config.ini_file, simulation_config.config, run_number)
    def get_sim_time_limit(simulation_config, run_number):
        # without a value, the config keeps its own limit, as without a store
        return limits.get(get_key(simulation_config, run_number)) or simulation_config.sim_time_limit
    def get_cpu_time_limit(simulation_config, run_number):
        return safety_cpu_time_limit if get_key(simulation_config, run_number) in limits else cpu_time_limit
    return get_sim_time_limit, get_cpu_time_limit

def get_smoke_test_tasks(cpu_time_limit="1s", run_number=None, sim_time_limits=None, **kwargs):
    """
    Returns multiple smoke test tasks matching the provided filter criteria. The returned tasks can be run by calling
    the :py:meth:`run <opp_repl.common.task.MultipleTasks.run>` method.

    Parameters:
        cpu_time_limit (string):
            The CPU-time limit of a run whose config has no simulation-time limit in the store of
            the project (see the module documentation).

        sim_time_limits (dict or None):
            Replaces the store of the simulation-time limits of the project, as
            :py:func:`read_smoke_test_sim_time_limits` returns it.

        kwargs (dict): The filter criteria parameters are inherited from the :py:meth:`get_simulation_tasks <opp_repl.simulation.task.get_simulation_tasks>` method.

    Returns (:py:class:`MultipleSimulationTestTasks <opp_repl.test.simulation.MultipleSimulationTestTasks>`):
        an object that contains a list of :py:class:`SimulationTestTask <opp_repl.test.simulation.SimulationTestTask>` objects matching the provided filter criteria.
        The result can be run (and re-run) without providing additional parameters.
    """
    if kwargs.get("sim_time_limit") is None:
        kwargs.pop("sim_time_limit", None)
        simulation_project = kwargs.get("simulation_project") or get_default_simulation_project()
        sim_time_limit, cpu_time_limit = get_smoke_test_time_limits(simulation_project, cpu_time_limit=cpu_time_limit, sim_time_limits=sim_time_limits)
        kwargs["sim_time_limit"] = sim_time_limit
    return get_simulation_test_tasks(cpu_time_limit=cpu_time_limit, run_number=run_number, name="smoke test", simulation_test_task_class=SmokeTestTask, **kwargs)
get_smoke_test_tasks.__signature__ = combine_signatures(get_smoke_test_tasks, get_simulation_test_tasks, get_simulation_tasks)

def run_smoke_tests(test_map_records=None, changes=None, test_map=None, ignore_environment=False, sample=None, **kwargs):
    """
    Runs one or more smoke tests that match the provided filter criteria.

    Parameters:
        test_map_records, changes, test_map, ignore_environment, sample:
            The options of the test map, as for
            :py:func:`opp_repl.test.fingerprint.task.run_fingerprint_tests`. The records of the
            smoke tests also serve the sanitizer tests, which stop at the same simulation time.

        kwargs (dict): The filter criteria parameters are inherited from the :py:func:`get_smoke_test_tasks` function.

    Returns (:py:class:`MultipleTestTaskResults <opp_repl.test.task.MultipleTestTaskResults>`):
        an object that contains a list of :py:class:`SimulationTestTaskResult <opp_repl.test.simulation.SimulationTestTaskResult>` objects. Each object describes the result of running one test task.
    """
    kwargs = apply_project_test_defaults("smoke", kwargs)
    multiple_test_tasks = get_smoke_test_tasks(**kwargs)
    if changes or test_map_records:
        # lazy: the test map imports the coverage module, which imports the simulation modules
        from opp_repl.test.test_map.select import apply_test_map_options
        kwargs = apply_test_map_options("smoke", multiple_test_tasks, kwargs, test_map_records=test_map_records, changes=changes, test_map=test_map, ignore_environment=ignore_environment, sample=sample)
    return multiple_test_tasks.run(**kwargs)
run_smoke_tests.__signature__ = combine_signatures(run_smoke_tests, get_smoke_test_tasks)

def _write_sim_time_limits(file_name, entries):
    os.makedirs(os.path.dirname(file_name), exist_ok=True)
    with open(file_name, "w") as f:
        # one entry on each line, so that a git diff shows one config on each line
        f.write("[\n" + ",\n".join(json.dumps(entry, sort_keys=True) for entry in entries) + "\n]\n")

def update_smoke_test_sim_time_limits(cpu_time_limit="1s", **kwargs):
    """
    Runs the smoke tests with only the CPU-time limit, and writes the simulation time that each run
    reached into the store of the simulation-time limits of the project (see the module
    documentation). Run it on the CI machine, in the mode of the smoke tests. A run that ends before
    the limit gets ``null``; an interactive config, and a run that does not get past the simulation
    time zero, get no value. The values of the configs that the filters leave out stay.

    Parameters:
        cpu_time_limit (string):
            The CPU-time limit of each run.

        kwargs (dict):
            The filter criteria parameters are inherited from the :py:func:`get_smoke_test_tasks` function.

    Returns (:py:class:`MultipleTestTaskResults <opp_repl.test.task.MultipleTestTaskResults>`):
        the results of the runs.
    """
    kwargs = apply_project_test_defaults("smoke", kwargs)
    simulation_project = kwargs["simulation_project"]
    file_name = get_smoke_test_sim_time_limits_file(simulation_project)
    if not file_name:
        raise Exception(f"The project {simulation_project.get_name()} has no store of simulation-time limits (test_parameters[\"smoke\"][\"sim_time_limits\"])")
    multiple_test_tasks = get_smoke_test_tasks(cpu_time_limit=cpu_time_limit, sim_time_limits={}, **kwargs)
    results = multiple_test_tasks.run(**kwargs)
    limits = read_smoke_test_sim_time_limits(simulation_project) or {}
    for test_task_result in results.results:
        simulation_task = test_task_result.task.simulation_task
        simulation_config = simulation_task.simulation_config
        key = _get_sim_time_limit_key(simulation_config.working_directory, simulation_config.ini_file, simulation_config.config, simulation_task.run_number)
        limits.pop(key, None)
        simulation_task_result = getattr(test_task_result, "simulation_task_result", None)
        if test_task_result.result == "SKIP" or simulation_task_result is None or simulation_task_result.subprocess_result is None:
            continue
        if simulation_task_result.time_limit_reached == "CPU time limit reached":
            sim_time = simulation_task_result.last_simulation_time
            if re.fullmatch(r"0+(\.0*)?[a-z]*", sim_time or "0"):
                continue
            limits[key] = sim_time
        elif simulation_task_result.time_limit_reached is None or simulation_task_result.time_limit_reached == "Simulation time limit reached":
            limits[key] = None
    entries = [{"working_directory": key[0], "ini_file": key[1], "config": key[2], "run_number": key[3], "sim_time_limit": limit} for key, limit in sorted(limits.items())]
    _write_sim_time_limits(file_name, entries)
    _logger.info(f"Wrote {len(entries)} simulation-time limits into {file_name}")
    return results
update_smoke_test_sim_time_limits.__signature__ = combine_signatures(update_smoke_test_sim_time_limits, get_smoke_test_tasks)
