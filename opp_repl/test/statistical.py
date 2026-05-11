"""
This module provides functionality for statistical testing of multiple simulations.

The main function is :py:func:`run_statistical_tests`. It allows running multiple statistical tests
matching the provided filter criteria. Statistical tests check if scalar results of the simulations
are the same as the saved baseline results. The baseline results can be found in the statistics folder
of the simulation project.
"""

import glob
import logging
import math
import pandas
import re
import shutil
import subprocess

try:
    from omnetpp.scave.results import *
except (ImportError, ModuleNotFoundError):
    pass

from opp_repl.simulation import *
from opp_repl.test.fingerprint import *
from opp_repl.test.simulation import *

_logger = logging.getLogger(__name__)
_append_args = [
    "--record-eventlog=false",
    "--output-scalar-precision=17",
    "--output-vector-precision=17",
    "--**.param-recording=false",
    "--output-scalar-file=${resultdir}/${inifile}-${configname}-#${repetition}.sca",
    "--output-vector-file=${resultdir}/${inifile}-${configname}-#${repetition}.vec"
]

def _read_scalar_result_file(file_name):
    df = read_result_files(file_name)
    df = get_scalars(df, include_runattrs=True)
    df = df if df.empty else df[["experiment", "measurement", "replication", "module", "name", "value"]]
    return df

def _write_diff_file(a_file_name, b_file_name, diff_file_name):
    diff_command = ["diff", a_file_name, b_file_name]
    with open(diff_file_name, "w") as file:
        subprocess.call(diff_command, stdout=file)

def _remove_attr_lines(file_path):
    with open(file_path, 'r') as file:
        lines = file.readlines()

    # Variables to track state
    new_lines = []
    in_attr_block = False
    attr_block_found = False

    for line in lines:
        if line.startswith('attr '):
            if not attr_block_found:
                if not in_attr_block:
                    in_attr_block = True
                new_lines.append(line)
            else:
                in_attr_block = False
        else:
            if in_attr_block:
                attr_block_found = True
            in_attr_block = False
            new_lines.append(line)

    with open(file_path, 'w') as file:
        file.writelines(new_lines)

class StatisticalTestTaskResult(SimulationTestTaskResult):
    """Result of a statistical test task.

    Stores the raw DataFrames so that the comparison can be re-run
    with different filter parameters without re-running the simulation.

    Attributes:
        stored_df (pd.DataFrame or None): The stored/baseline scalar DataFrame.
        current_df (pd.DataFrame or None): The current scalar DataFrame.
        comparison (ScalarComparisonResult or None): The comparison result.
    """

    def _compute_verdict(self, comparison):
        """Compute result and reason from a ScalarComparisonResult."""
        has_differences = not comparison.different.empty or not comparison.added.empty or not comparison.removed.empty
        if has_differences:
            self.result = "FAIL"
        else:
            self.result = "PASS"
        parts = []
        if not comparison.identical.empty:
            parts.append(f"{len(comparison.identical)} compared")
        if not comparison.added.empty:
            parts.append(f"{len(comparison.added)} added")
        if not comparison.removed.empty:
            parts.append(f"{len(comparison.removed)} removed")
        if comparison.num_filtered_out:
            parts.append(f"{comparison.num_filtered_out} filtered out")
        if comparison.num_below_threshold:
            parts.append(f"{comparison.num_below_threshold} below threshold")
        if not comparison.different.empty:
            parts.append(f"{len(comparison.different)} different")
            df = comparison.different
            id = df["unbounded_relative_error"].idxmax()
            if math.isnan(id):
                id = next(iter(df.index), None)
            detail = df.loc[id].to_string()
            detail = re.sub(r" +", " = ", detail)
            detail = re.sub(r"\n", ", ", detail)
            parts.append("largest difference: " + detail)
        self.reason = ", ".join(parts) if parts else None
        self.expected = self.expected_result == self.result
        self.color = self.possible_result_colors[self.possible_results.index(self.result)]

    def recheck(self, **kwargs):
        """Re-run the statistical comparison with new filter parameters.

        Accepts the same filter keyword arguments as
        :py:func:`~opp_repl.common.util.compare_scalar_dataframes`:
        ``name_filter``, ``exclude_name_filter``, ``module_filter``,
        ``exclude_module_filter``, ``full_match``,
        ``unbounded_relative_error_threshold``.

        Returns:
            StatisticalTestTaskResult: A new result with the updated verdict.
            Returns a copy of self unchanged if re-filtering is not possible.
        """
        import copy
        new_result = copy.copy(self)
        if self.stored_df is None or self.current_df is None:
            return new_result
        if self.stored_df.empty:
            return new_result
        if self.current_df.empty:
            return new_result
        comparison = compare_scalar_dataframes(self.stored_df, self.current_df, suffixes=('_stored', '_current'), **kwargs)
        new_result.comparison = comparison
        new_result._compute_verdict(comparison)
        return new_result

class MultipleStatisticalTestTaskResults(MultipleSimulationTestTaskResults):
    """Multiple statistical test task results with bulk re-filtering support."""

    def recheck(self, **kwargs):
        """Re-run the statistical comparison on all results with new filter parameters.

        Accepts the same filter keyword arguments as
        :py:func:`StatisticalTestTaskResult.recheck`.

        Returns:
            MultipleStatisticalTestTaskResults: A new results object with updated verdicts.
        """
        new_results = [result.recheck(**kwargs) if hasattr(result, 'recheck') else result for result in self.results]
        return MultipleStatisticalTestTaskResults(multiple_tasks=self.multiple_tasks, results=new_results)

class StatisticalTestTask(SimulationTestTask):
    def __init__(self, simulation_config=None, run_number=0, name="statistical test", task_result_class=StatisticalTestTaskResult, **kwargs):
        super().__init__(simulation_task=SimulationTask(simulation_config=simulation_config, run_number=run_number, name=name, **kwargs), task_result_class=task_result_class, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs

    def get_result_file_name(self, extension):
        simulation_config = self.simulation_task.simulation_config
        return f"{simulation_config.ini_file}-{simulation_config.config}-#{self.simulation_task.run_number}.{extension}"

    def check_simulation_task_result(self, simulation_task_result, baseline_simulation_project=None, result_name_filter=None, exclude_result_name_filter=None, result_module_filter=None, exclude_result_module_filter=None, full_match=False, unbounded_relative_error_threshold=None, **kwargs):
        simulation_config = self.simulation_task.simulation_config
        simulation_project = simulation_config.simulation_project
        baseline_project = baseline_simulation_project or simulation_project
        working_directory = simulation_config.working_directory
        current_scalar_result_file_name = simulation_project.get_full_path(os.path.join(working_directory, "results", self.get_result_file_name("sca")))
        current_vector_result_file_name = simulation_project.get_full_path(os.path.join(working_directory, "results", self.get_result_file_name("vec")))
        current_index_result_file_name = simulation_project.get_full_path(os.path.join(working_directory, "results", self.get_result_file_name("vci")))
        if os.path.exists(current_vector_result_file_name):
            run_command_with_logging(["opp_scavetool", "x", "--precision=17", "--type", "sth", "-w", current_scalar_result_file_name, current_vector_result_file_name, "-o", current_scalar_result_file_name])
            os.remove(current_vector_result_file_name)
        else:
            run_command_with_logging(["opp_scavetool", "x", "--precision=17", "--type", "sth", "-w", current_scalar_result_file_name, "-o", current_scalar_result_file_name])
        if os.path.exists(current_index_result_file_name):
            os.remove(current_index_result_file_name)
        _remove_attr_lines(current_scalar_result_file_name)
        stored_scalar_result_file_name = baseline_project.get_full_path(os.path.join(baseline_project.statistics_folder, working_directory, self.get_result_file_name("sca")))
        _logger.debug(f"Reading result file {current_scalar_result_file_name}")
        current_df = _read_scalar_result_file(current_scalar_result_file_name)
        stored_df = None
        comparison = None
        scalar_result_diff_file_name = re.sub(r".sca$", ".diff", stored_scalar_result_file_name)
        if os.path.exists(scalar_result_diff_file_name):
            os.remove(scalar_result_diff_file_name)
        if os.path.exists(stored_scalar_result_file_name):
            _logger.debug(f"Reading result file {stored_scalar_result_file_name}")
            stored_df = _read_scalar_result_file(stored_scalar_result_file_name)
            if not current_df.equals(stored_df):
                _write_diff_file(stored_scalar_result_file_name, current_scalar_result_file_name, scalar_result_diff_file_name)
                _logger.debug(f"Writing diff file {scalar_result_diff_file_name}")
                if current_df.empty:
                    task_result = self.task_result_class(task=self, simulation_task_result=simulation_task_result, result="FAIL", reason="Current statistical results are empty")
                elif stored_df.empty:
                    task_result = self.task_result_class(task=self, simulation_task_result=simulation_task_result, result="FAIL", reason="Stored statistical results are empty")
                else:
                    comparison = compare_scalar_dataframes(stored_df, current_df, suffixes=('_stored', '_current'),
                                                          name_filter=result_name_filter, exclude_name_filter=exclude_result_name_filter,
                                                          module_filter=result_module_filter, exclude_module_filter=exclude_result_module_filter,
                                                          full_match=full_match, unbounded_relative_error_threshold=unbounded_relative_error_threshold)
                    task_result = self.task_result_class(task=self, simulation_task_result=simulation_task_result)
                    task_result._compute_verdict(comparison)
                    if not comparison.different.empty:
                        scalar_result_csv_file_name = re.sub(r".sca$", ".csv", stored_scalar_result_file_name)
                        _logger.debug(f"Writing CSV file {scalar_result_csv_file_name}")
                        comparison.different.to_csv(scalar_result_csv_file_name, float_format="%.17g")
            else:
                task_result = self.task_result_class(task=self, simulation_task_result=simulation_task_result, result="PASS")
        else:
            task_result = self.task_result_class(task=self, simulation_task_result=simulation_task_result, result="ERROR", reason="Stored statistical results are not found")
        task_result.stored_df = stored_df
        task_result.current_df = current_df
        task_result.comparison = comparison
        if os.path.exists(current_scalar_result_file_name):
            os.remove(current_scalar_result_file_name)
        return task_result

def get_statistical_test_sim_time_limit(simulation_config, run_number=0):
    return simulation_config.sim_time_limit

def get_statistical_test_tasks(sim_time_limit=get_statistical_test_sim_time_limit, run_number=0, **kwargs):
    """
    Returns multiple statistical test tasks matching the provided filter criteria. The returned tasks can be run by
    calling the :py:meth:`run <opp_repl.common.task.MultipleTasks.run>` method.

    Parameters:
        kwargs (dict):
            The filter criteria parameters are inherited from the :py:meth:`get_simulation_tasks <opp_repl.simulation.task.get_simulation_tasks>` method.

    Returns (:py:class:`MultipleTestTasks`):
        an object that contains a list of :py:class:`StatisticalTestTask` objects matching the provided filter criteria.
        The result can be run (and re-run) without providing additional parameters.
    """
    return get_simulation_tasks(name="statistical test", run_number=run_number, sim_time_limit=sim_time_limit, simulation_task_class=StatisticalTestTask, multiple_simulation_tasks_class=MultipleSimulationTestTasks, multiple_task_results_class=MultipleStatisticalTestTaskResults, **kwargs)
get_statistical_test_tasks.__signature__ = combine_signatures(get_statistical_test_tasks, get_simulation_tasks)

def run_statistical_tests(append_args=[], **kwargs):
    """
    Runs one or more statistical tests that match the provided filter criteria.

    Parameters:
        kwargs (dict):
            The filter criteria parameters are inherited from the :py:func:`get_statistical_test_tasks` function.

    Returns (:py:class:`MultipleSimulationTestTaskResults`):
        an object that contains a list of :py:class:`SimulationTestTaskResult` objects. Each object describes the result of running one test task.
    """
    multiple_statistical_test_tasks = get_statistical_test_tasks(**kwargs)
    return multiple_statistical_test_tasks.run(append_args=append_args + _append_args, **kwargs)
run_statistical_tests.__signature__ = combine_signatures(run_statistical_tests, get_statistical_test_tasks)

class StatisticalResultsUpdateTask(SimulationUpdateTask):
    def __init__(self, simulation_config=None, run_number=0, name="statistical results update", **kwargs):
        super().__init__(simulation_task=SimulationTask(simulation_config=simulation_config, run_number=run_number, name=name, **kwargs), simulation_config=simulation_config, run_number=run_number, name=name, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs

    def get_result_file_name(self, extension):
        simulation_config = self.simulation_task.simulation_config
        return f"{simulation_config.ini_file}-{simulation_config.config}-#{self.simulation_task.run_number}.{extension}"

    def run_protected(self, baseline_simulation_project=None, **kwargs):
        simulation_config = self.simulation_task.simulation_config
        simulation_project = simulation_config.simulation_project
        baseline_project = baseline_simulation_project or simulation_project
        working_directory = simulation_config.working_directory
        target_results_directory = baseline_project.get_full_path(os.path.join(baseline_project.statistics_folder, working_directory))
        os.makedirs(target_results_directory, exist_ok=True)
        update_result = super().run_protected(**kwargs)
        stored_scalar_result_file_name = simulation_project.get_full_path(os.path.join(working_directory, "results", self.get_result_file_name("sca")))
        if update_result.result == "INSERT" or update_result.result == "UPDATE":
            shutil.copy(stored_scalar_result_file_name, target_results_directory)
        if os.path.exists(stored_scalar_result_file_name):
            os.remove(stored_scalar_result_file_name)
        return update_result

    def check_simulation_task_result(self, simulation_task_result, baseline_simulation_project=None, result_name_filter=None, exclude_result_name_filter=None, result_module_filter=None, exclude_result_module_filter=None, full_match=False, **kwargs):
        simulation_config = self.simulation_task.simulation_config
        simulation_project = simulation_config.simulation_project
        baseline_project = baseline_simulation_project or simulation_project
        working_directory = simulation_config.working_directory
        current_scalar_result_file_name = simulation_project.get_full_path(os.path.join(working_directory, "results", self.get_result_file_name("sca")))
        current_vector_result_file_name = simulation_project.get_full_path(os.path.join(working_directory, "results", self.get_result_file_name("vec")))
        current_index_result_file_name = simulation_project.get_full_path(os.path.join(working_directory, "results", self.get_result_file_name("vci")))
        if os.path.exists(current_vector_result_file_name):
            run_command_with_logging(["opp_scavetool", "x", "--precision=17", "--type", "sth", "-w", current_scalar_result_file_name, current_vector_result_file_name, "-o", current_scalar_result_file_name])
            os.remove(current_vector_result_file_name)
        else:
            run_command_with_logging(["opp_scavetool", "x", "--precision=17", "--type", "sth", "-w", current_scalar_result_file_name, "-o", current_scalar_result_file_name])
        if os.path.exists(current_index_result_file_name):
            os.remove(current_index_result_file_name)
        _remove_attr_lines(current_scalar_result_file_name)
        stored_scalar_result_file_name = baseline_project.get_full_path(os.path.join(baseline_project.statistics_folder, working_directory, self.get_result_file_name("sca")))
        _logger.debug(f"Reading result file {current_scalar_result_file_name}")
        current_df = _read_scalar_result_file(current_scalar_result_file_name)
        scalar_result_diff_file_name = re.sub(r".sca$", ".diff", stored_scalar_result_file_name)
        if os.path.exists(scalar_result_diff_file_name):
            os.remove(scalar_result_diff_file_name)
        if not os.path.exists(stored_scalar_result_file_name):
            return self.task_result_class(task=self, simulation_task_result=simulation_task_result, result="INSERT")
        else:
            _logger.debug(f"Reading result file {stored_scalar_result_file_name}")
            stored_df = _read_scalar_result_file(stored_scalar_result_file_name)
            if not current_df.equals(stored_df):
                _write_diff_file(stored_scalar_result_file_name, current_scalar_result_file_name, scalar_result_diff_file_name)
                return self.task_result_class(task=self, simulation_task_result=simulation_task_result, result="UPDATE")
            else:
                return self.task_result_class(task=self, simulation_task_result=simulation_task_result, result="KEEP")

def get_update_statistical_result_tasks(run_number=0, **kwargs):
    """
    Returns multiple update statistical results tasks matching the provided filter criteria. The returned tasks can be run by
    calling the :py:meth:`run <opp_repl.common.task.MultipleTasks.run>` method.

    Parameters:
        kwargs (dict):
            The filter criteria parameters are inherited from the :py:meth:`get_simulation_tasks <opp_repl.simulation.task.get_simulation_tasks>` method.

    Returns (:py:class:`MultipleUpdateTasks`):
        an object that contains a list of :py:class:`StatisticalResultsUpdateTask` objects matching the provided filter criteria.
        The result can be run (and re-run) without providing additional parameters.
    """
    return get_simulation_tasks(run_number=run_number, multiple_simulation_tasks_class=MultipleSimulationUpdateTasks, simulation_task_class=StatisticalResultsUpdateTask, **kwargs)
get_update_statistical_result_tasks.__signature__ = combine_signatures(get_update_statistical_result_tasks, get_simulation_tasks)

def update_statistical_test_results(sim_time_limit=get_statistical_test_sim_time_limit, append_args=[], **kwargs):
    """
    Updates the stored statistical results for one or more chart tests that match the provided filter criteria.

    Parameters:
        kwargs (dict):
            The filter criteria parameters are inherited from the :py:func:`get_update_statistical_result_tasks` function.

    Returns (:py:class:`MultipleUpdateTaskResults`):
        an object that contains a list of :py:class:`UpdateTaskResult` objects. Each object describes the result of running one update task.
    """
    multiple_update_statistical_result_tasks = get_update_statistical_result_tasks(sim_time_limit=sim_time_limit, **kwargs)
    return multiple_update_statistical_result_tasks.run(sim_time_limit=sim_time_limit, append_args=append_args + _append_args, **kwargs)
update_statistical_test_results.__signature__ = combine_signatures(update_statistical_test_results, get_update_statistical_result_tasks)
