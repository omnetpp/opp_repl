import logging

from opp_repl.simulation import *
from opp_repl.test.simulation import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

class SanitizerTestTask(SimulationTestTask):
    def run_protected(self, output_stream=sys.stdout, append_args=[], **kwargs):
        simulation_task_result = self.simulation_task.run_protected(output_stream=output_stream, append_args=no_result_files_append_args + append_args, **kwargs)
        stderr = simulation_task_result.subprocess_result.stderr or ""
        test_task_result = super().check_simulation_task_result(simulation_task_result, **kwargs)
        match = re.search(r"SUMMARY: (.*)", stderr)
        if match:
            test_task_result.reason = re.sub(r" in", "", match.group(1))
            # TODO isn't there a better way?
            if test_task_result.result == "PASS":
                test_task_result.result = "FAIL"
                test_task_result.expected = False
                test_task_result.color = COLOR_YELLOW
        return test_task_result

def get_sanitizer_test_tasks(mode="sanitize", cpu_time_limit="1s", run_number=None, sim_time_limits=None, **kwargs):
    # the sanitizer tests stop where the smoke tests stop (the store of the simulation-time limits)
    from opp_repl.test.smoke import get_smoke_test_time_limits
    if kwargs.get("sim_time_limit") is None:
        kwargs.pop("sim_time_limit", None)
        simulation_project = kwargs.get("simulation_project") or get_default_simulation_project()
        sim_time_limit, cpu_time_limit = get_smoke_test_time_limits(simulation_project, cpu_time_limit=cpu_time_limit, sim_time_limits=sim_time_limits)
        kwargs["sim_time_limit"] = sim_time_limit
    return get_simulation_test_tasks(mode=mode, cpu_time_limit=cpu_time_limit, name="sanitizer test", simulation_test_task_class=SanitizerTestTask, run_number=run_number, **kwargs)
get_sanitizer_test_tasks.__signature__ = combine_signatures(get_sanitizer_test_tasks, get_simulation_test_tasks, get_simulation_tasks)

def run_sanitizer_tests(changes=None, test_map=None, ignore_environment=False, **kwargs):
    """
    Runs the sanitizer tests. With *changes*, only the selected tests run, as for
    :py:func:`opp_repl.test.fingerprint.task.run_fingerprint_tests`; the test map gives the
    sanitizer tests the records of the smoke tests, which stop at the same simulation time.
    """
    kwargs = apply_project_test_defaults("sanitizer", kwargs)
    multiple_test_tasks = get_sanitizer_test_tasks(**kwargs)
    if changes:
        # lazy: the test map imports the coverage module, which imports the simulation modules
        from opp_repl.test.test_map.select import apply_test_map_options
        kwargs = apply_test_map_options("sanitizer", multiple_test_tasks, kwargs, changes=changes, test_map=test_map, ignore_environment=ignore_environment)
    return multiple_test_tasks.run(**kwargs)
run_sanitizer_tests.__signature__ = combine_signatures(run_sanitizer_tests, get_sanitizer_test_tasks)
