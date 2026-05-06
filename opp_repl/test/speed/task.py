import logging

from opp_repl.simulation import *
from opp_repl.test.simulation import *
from opp_repl.test.task import *
from opp_repl.test.speed.store import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

_speed_test_append_args = ["-s", "-S", "--measure-cpu-usage=true",
                           "--cmdenv-express-mode=true", "--cmdenv-performance-display=false", "--cmdenv-status-frequency=1000000s",
                           "--record-vector-results=false", "--record-scalar-results=false", "--record-eventlog=false",
                           "--vector-recording=false", "--scalar-recording=false", "--bin-recording=false", "--param-recording=false"]

class SpeedTestTaskResult(SimulationTestTaskResult):
    """Result of a speed test task.

    Stores the measured and expected instruction counts so the verdict
    can be recomputed with a different tolerance without re-running.

    Attributes:
        num_cpu_instructions (int): Measured CPU instruction count.
        expected_num_cpu_instructions (int): Baseline CPU instruction count.
    """

    def _compute_verdict(self, max_relative_error=0.1):
        """Compute result and reason from stored instruction counts."""
        if (self.num_cpu_instructions - self.expected_num_cpu_instructions) / self.expected_num_cpu_instructions > max_relative_error:
            self.result = "FAIL"
            self.reason = f"Number of CPU instructions is too large: {self.num_cpu_instructions} > {self.expected_num_cpu_instructions}"
        elif (self.expected_num_cpu_instructions - self.num_cpu_instructions) / self.expected_num_cpu_instructions > max_relative_error:
            self.result = "FAIL"
            self.reason = f"Number of CPU instructions is too small: {self.num_cpu_instructions} < {self.expected_num_cpu_instructions}"
        else:
            self.result = "PASS"
            self.reason = None
        self.expected = self.expected_result == self.result
        self.color = self.possible_result_colors[self.possible_results.index(self.result)]

    def recheck(self, max_relative_error=0.1, **kwargs):
        """Recompute the speed test verdict with a different tolerance.

        Args:
            max_relative_error (float): Maximum allowed relative difference
                between measured and expected instruction counts (default 0.1).

        Returns:
            SpeedTestTaskResult: A new result with the updated verdict.
        """
        import copy
        new_result = copy.copy(self)
        if self.num_cpu_instructions is None or self.expected_num_cpu_instructions is None:
            return new_result
        new_result._compute_verdict(max_relative_error)
        return new_result

class SpeedTestTask(SimulationTestTask):
    def __init__(self, expected_num_cpu_instructions=None, max_relative_error=0.1, task_result_class=SpeedTestTaskResult, **kwargs):
        super().__init__(task_result_class=task_result_class, **kwargs)
        self.expected_num_cpu_instructions = expected_num_cpu_instructions
        self.max_relative_error = max_relative_error

    def check_simulation_task_result(self, simulation_task_result, **kwargs):
        task_result = self.task_result_class(task=self, simulation_task_result=simulation_task_result, expected_result="PASS")
        task_result.num_cpu_instructions = simulation_task_result.num_cpu_instructions
        task_result.expected_num_cpu_instructions = self.expected_num_cpu_instructions
        task_result._compute_verdict(self.max_relative_error)
        return task_result

    def run_protected(self, **kwargs):
        return super().run_protected(nice=-10, append_args=_speed_test_append_args, **kwargs)

def get_speed_test_tasks(mode="profile", run_number=0, baseline_simulation_project=None, **kwargs):
    multiple_simulation_tasks = get_simulation_tasks(name="speed test", mode=mode, run_number=run_number, **kwargs)
    simulation_project = multiple_simulation_tasks.simulation_project
    baseline_project = baseline_simulation_project or simulation_project
    speed_measurement_store = get_speed_measurement_store(baseline_project)
    tasks = []
    for simulation_task in multiple_simulation_tasks.tasks:
        simulation_config = simulation_task.simulation_config
        expected_num_cpu_instructions = speed_measurement_store.get_num_cpu_instructions(working_directory=simulation_config.working_directory, ini_file=simulation_config.ini_file, config=simulation_config.config, run_number=simulation_task.run_number)
        tasks.append(SpeedTestTask(simulation_task=simulation_task, expected_num_cpu_instructions=expected_num_cpu_instructions, **dict(kwargs, simulation_project=simulation_project, mode=mode)))
    return MultipleSimulationTestTasks(tasks=tasks, **dict(kwargs, simulation_project=simulation_project, mode=mode))
get_speed_test_tasks.__signature__ = combine_signatures(get_speed_test_tasks, get_simulation_tasks)

def run_speed_tests(**kwargs):
    multiple_test_tasks = get_speed_test_tasks(**kwargs)
    return multiple_test_tasks.run(**kwargs)
run_speed_tests.__signature__ = combine_signatures(run_speed_tests, get_speed_test_tasks)

class SpeedUpdateTask(SimulationUpdateTask):
    def __init__(self, action="Updating speed", **kwargs):
        super().__init__(action=action, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs

    def run_protected(self, **kwargs):
        simulation_config = self.simulation_task.simulation_config
        simulation_project = simulation_config.simulation_project
        start_time = time.time()
        simulation_task_result = self.simulation_task.run_protected(nice=-10, append_args=_speed_test_append_args, **kwargs)
        end_time = time.time()
        simulation_task_result.elapsed_wall_time = end_time - start_time
        speed_measurement_store = get_speed_measurement_store(simulation_project)
        expected_num_cpu_instructions = speed_measurement_store.find_num_cpu_instructions(working_directory=simulation_config.working_directory, ini_file=simulation_config.ini_file, config=simulation_config.config, run_number=self.simulation_task.run_number)
        return SpeedUpdateTaskResult(task=self, simulation_task_result=simulation_task_result, expected_num_cpu_instructions=expected_num_cpu_instructions, num_cpu_instructions=simulation_task_result.num_cpu_instructions)

class MultipleSpeedUpdateTasks(MultipleSimulationUpdateTasks):
    def __init__(self, multiple_simulation_tasks=None, name="update speed", **kwargs):
        super().__init__(name=name, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.multiple_simulation_tasks = multiple_simulation_tasks

    def run(self, simulation_project=None, build=None, **kwargs):
        simulation_project = simulation_project or self.multiple_simulation_tasks.simulation_project
        if build if build is not None else get_default_build_argument():
            simulation_project.build(mode="profile")
        multiple_speed_update_results = super().run(**kwargs)
        speed_measurement_store = get_speed_measurement_store(simulation_project)
        for speed_update_result in multiple_speed_update_results.results:
            simulation_task_result = speed_update_result.simulation_task_result
            speed_update_task = speed_update_result.task
            simulation_task = speed_update_task.simulation_task
            simulation_config = simulation_task.simulation_config
            if simulation_task_result.elapsed_wall_time:
                speed_measurement_store.update_entry(elapsed_wall_time=simulation_task_result.elapsed_wall_time, elapsed_cpu_time=simulation_task_result.elapsed_cpu_time, num_cpu_cycles=simulation_task_result.num_cpu_cycles, num_cpu_instructions=simulation_task_result.num_cpu_instructions,
                                                     test_result="PASS", sim_time_limit=simulation_task.sim_time_limit,
                                                     working_directory=simulation_config.working_directory, ini_file=simulation_config.ini_file, config=simulation_config.config, run_number=simulation_task.run_number)
        speed_measurement_store.write()
        return speed_measurement_store

class SpeedUpdateTaskResult(SimulationUpdateTaskResult):
    def __init__(self, expected_num_cpu_instructions=None, num_cpu_instructions=None, reason=None, max_relative_error=0.1, **kwargs):
        super().__init__(**kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        if expected_num_cpu_instructions is None:
            self.result = "INSERT"
            self.reason = None
            self.color = COLOR_YELLOW
        elif abs(expected_num_cpu_instructions - num_cpu_instructions) / expected_num_cpu_instructions > max_relative_error:
            self.result = "UPDATE"
            self.reason = None
            self.color = COLOR_YELLOW
        else:
            self.result = "KEEP"
            self.reason = None
            self.color = COLOR_GREEN
        self.expected = self.result == self.expected_result

    def get_description(self, complete_error_message=True, include_parameters=False, **kwargs):
        return (self.task.simulation_task.get_parameters_string() + " " if include_parameters else "") + \
               self.color + self.result + COLOR_RESET + \
               ((" " + self.simulation_task_result.get_error_message(complete_error_message=complete_error_message)) if self.simulation_task_result and self.simulation_task_result.result == "ERROR" else "") + \
               (" (" + self.reason + ")" if self.reason else "")

    def __repr__(self):
        return "Speed update result: " + self.get_description(include_parameters=True)

    def print_result(self, complete_error_message=True, output_stream=sys.stdout, **kwargs):
        print(self.get_description(complete_error_message=complete_error_message), file=output_stream)

def get_update_speed_results_tasks(mode="profile", run_number=0, **kwargs):
    update_tasks = []
    multiple_simulation_tasks = get_simulation_tasks(mode=mode, run_number=run_number, **kwargs)
    for simulation_task in multiple_simulation_tasks.tasks:
        update_task = SpeedUpdateTask(simulation_task=simulation_task, **kwargs)
        update_tasks.append(update_task)
    return MultipleSpeedUpdateTasks(multiple_simulation_tasks, tasks=update_tasks, **kwargs)
get_update_speed_results_tasks.__signature__ = combine_signatures(get_update_speed_results_tasks, get_simulation_tasks)

def update_speed_test_results(**kwargs):
    multiple_speed_update_tasks = get_update_speed_results_tasks(**kwargs)
    return multiple_speed_update_tasks.run(**kwargs)
update_speed_test_results.__signature__ = combine_signatures(update_speed_test_results, get_update_speed_results_tasks)
