"""
Compare simulation results between two simulation projects or git versions.

This module runs matching simulation configs in both projects and compares
three aspects: stdout trajectories, fingerprint trajectories, and statistical
(scalar) results.

Quick examples
--------------

Compare two arbitrary projects::

    results = compare_simulations(
        simulation_project_1=project_a,
        simulation_project_2=project_b,
        working_directory_filter="simulations/nr/.*",
        config_filter="General",
        run_number=0)

Compare two git commits of the same project::

    simu5g = get_simulation_project("simu5g")
    results = compare_simulations_between_commits(simu5g, "HEAD~1", "HEAD",
                                   config_filter="General",
                                   run_number=0)

Analyze the results::

    r = results.results[0]
    print(r)                            # overall summary
    print(r.stdout_trajectory_comparison_result)       # IDENTICAL / DIVERGENT
    print(r.fingerprint_trajectory_comparison_result)  # IDENTICAL / DIVERGENT
    print(r.statistical_comparison_result)             # IDENTICAL / DIFFERENT
    r.print_different_statistical_results(include_relative_errors=True)

See :py:func:`compare_simulations`, :py:func:`compare_simulations_between_commits`, and
:py:class:`CompareSimulationsTaskResult` for full details.
"""

import copy

try:
    from omnetpp.scave.results import *
except (ImportError, ModuleNotFoundError):
    pass

from opp_repl.common.util import *
from opp_repl.simulation.task import *
from opp_repl.test.fingerprint.task import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

class CompareSimulationsTaskResult(TaskResult):
    """Result of comparing two simulation runs.

    The overall verdict is stored in ``result`` (``"IDENTICAL"``,
    ``"DIVERGENT"``, or ``"DIFFERENT"``) with a human-readable ``reason``.

    Stdout trajectory::

        r.stdout_trajectory_comparison_result   # "IDENTICAL" or "DIVERGENT"
        r.stdout_trajectory_divergence_position  # divergence event or None
        r.stdout_trajectory_divergence_position.get_description()
        r.debug_at_stdout_divergence_position()
        r.run_until_stdout_divergence_position()

    Fingerprint trajectory::

        r.fingerprint_trajectory_comparison_result   # "IDENTICAL" or "DIVERGENT"
        r.fingerprint_trajectory_divergence_position  # divergence event or None
        r.fingerprint_trajectory_divergence_position.get_description()
        r.print_divergence_position_cause_chain()
        r.show_divergence_position_in_sequence_chart()
        r.debug_at_fingerprint_divergence_position()
        r.run_until_fingerprint_divergence_position()

    Statistical (scalar) differences::

        r.statistical_comparison_result        # "IDENTICAL" or "DIFFERENT"
        r.different_statistical_results        # DataFrame sorted by relative_error
        r.identical_statistical_results        # DataFrame of matching scalars
        r.df_1, r.df_2                         # raw scalar DataFrames
        r.print_different_statistic_modules()
        r.print_different_statistic_names()
        r.print_different_statistical_results(include_relative_errors=True,
                                              include_absolute_errors=True)
    """
    def __init__(self, multiple_task_results=None, **kwargs):
        super().__init__(expected_result="IDENTICAL", **kwargs)
        self.multiple_task_results = multiple_task_results
        if multiple_task_results and multiple_task_results.result == "DONE":
            self.multiple_tasks = multiple_task_results.multiple_tasks

            if self.task.compare_stdout:
                self._compute_stdout_verdict(**self.multiple_tasks.kwargs)
            else:
                self.stdout_trajectory_divergence_position = None
                self.stdout_trajectory_comparison_result = None
                self.stdout_trajectory_comparison_color = None

            if self.task.compare_fingerprint:
                self.fingerprint_trajectory_divergence_position = self._find_fingerprint_trajectory_divergence_position(**self.multiple_tasks.kwargs)
                if self.fingerprint_trajectory_divergence_position:
                    self.fingerprint_trajectory_comparison_result = "DIVERGENT"
                    self.fingerprint_trajectory_comparison_color = COLOR_YELLOW
                else:
                    self.fingerprint_trajectory_comparison_result = "IDENTICAL"
                    self.fingerprint_trajectory_comparison_color = COLOR_GREEN
            else:
                self.fingerprint_trajectory_divergence_position = None
                self.fingerprint_trajectory_comparison_result = None
                self.fingerprint_trajectory_comparison_color = None

            if self.task.compare_statistics:
                self._compute_statistical_verdict(**self.multiple_tasks.kwargs)
            else:
                self.different_statistical_results = pd.DataFrame()
                self.statistical_comparison_result = None
                self.statistical_comparison_color = None

            self._recompute_overall_result()
        else:
            self.stdout_trajectory_divergence_position = None
            self.stdout_trajectory_comparison_result = None
            self.stdout_trajectory_comparison_color = None
            self.fingerprint_trajectory_divergence_position = None
            self.fingerprint_trajectory_comparison_result = None
            self.fingerprint_trajectory_comparison_color = None
            self.different_statistical_results = pd.DataFrame()
            self.statistical_comparison_result = None
            self.statistical_comparison_color = None
            if multiple_task_results:
                self.result = multiple_task_results.result
                self.color = multiple_task_results.color
        self.expected = self.result == "IDENTICAL"

    def __repr__(self):
        if self.stdout_trajectory_divergence_position:
            stdout_trajectory_divergence_description = f"\nStdout trajectory comparison result: {self.stdout_trajectory_comparison_color}{self.stdout_trajectory_comparison_result}{COLOR_RESET}\n{self.stdout_trajectory_divergence_position.get_description()}"
        elif self.stdout_trajectory_comparison_result:
            stdout_trajectory_divergence_description = f"\nStdout trajectory comparison result: {self.stdout_trajectory_comparison_color}{self.stdout_trajectory_comparison_result}{COLOR_RESET}"
        else:
            stdout_trajectory_divergence_description = ""
        if self.fingerprint_trajectory_divergence_position:
            fingerprint_trajectory_divergence_description = f"\nFingerprint trajectory comparison result: {self.fingerprint_trajectory_comparison_color}{self.fingerprint_trajectory_comparison_result}{COLOR_RESET}\n{self.fingerprint_trajectory_divergence_position.get_description()}\n"
        elif self.fingerprint_trajectory_comparison_result:
            fingerprint_trajectory_divergence_description = f"\nFingerprint trajectory comparison result: {self.fingerprint_trajectory_comparison_color}{self.fingerprint_trajectory_comparison_result}{COLOR_RESET}"
        else:
            fingerprint_trajectory_divergence_description = ""
        if not self.different_statistical_results.empty:
            max_num_different_statistics = 3
            different_unique_modules = self.different_statistical_results["module"].unique()
            different_unique_statistics = self.different_statistical_results["name"].unique()
            different_modules = ", ".join(map(lambda s: f"{COLOR_CYAN}{s}{COLOR_RESET}", different_unique_modules[0:max_num_different_statistics])) + (", ..." if len(different_unique_modules) > max_num_different_statistics else "")
            different_statistics = ", ".join(map(lambda s: f"{COLOR_GREEN}{s}{COLOR_RESET}", different_unique_statistics[0:max_num_different_statistics])) + (", ..." if len(different_unique_statistics) > max_num_different_statistics else "")
            statistical_desription = f"\nStatistical comparison result: {self.statistical_comparison_color}{self.statistical_comparison_result}{COLOR_RESET}, summary: {str(len(self.df_1))} and {str(len(self.df_2))} TOTAL, {COLOR_GREEN}{str(len(self.identical_statistical_results))} IDENTICAL{COLOR_RESET}, {COLOR_YELLOW}{str(len(self.different_statistical_results))} DIFFERENT{COLOR_RESET}, some differences: {different_statistics} in {different_modules}"
        elif self.statistical_comparison_result:
            statistical_desription = f"\nStatistical comparison result: {self.statistical_comparison_color}{self.statistical_comparison_result}{COLOR_RESET}"
        else:
            statistical_desription = ""
        return TaskResult.__repr__(self) + "\n" + stdout_trajectory_divergence_description + fingerprint_trajectory_divergence_description + statistical_desription

    def recompare(self, **kwargs):
        """Re-run the comparison with new filter parameters.

        Recomputes the stdout trajectory comparison (if ``stdout_filter`` or
        ``exclude_stdout_filter`` are provided) and the statistical comparison
        (if any of the statistical filter parameters are provided) using the
        already-available simulation output.  Returns a **new** result object;
        the original is unchanged.

        Keyword Args:
            stdout_filter (str or None): Regex to include only matching stdout lines.
            exclude_stdout_filter (str or None): Regex to exclude matching stdout lines.
            statistical_result_name_filter (str or None): Regex for scalar names.
            exclude_statistic_name_filter (str or None): Regex to exclude scalar names.
            statistical_result_module_filter (str or None): Regex for modules.
            exclude_statistic_module_filter (str or None): Regex to exclude modules.
            full_match (bool): Use ``re.fullmatch`` instead of ``re.search``.

        Returns:
            CompareSimulationsTaskResult: A new result with updated verdicts.
        """
        import copy
        new_result = copy.copy(self)
        if self.task.compare_stdout:
            new_result._compute_stdout_verdict(**kwargs)
        if self.task.compare_statistics:
            new_result._compute_statistical_verdict(**kwargs)
        new_result._recompute_overall_result()
        return new_result

    def _compute_stdout_verdict(self, **kwargs):
        """Compute stdout trajectory comparison verdict."""
        self.stdout_trajectory_divergence_position = self._find_stdout_trajectory_divergence_position(**kwargs)
        if self.stdout_trajectory_divergence_position:
            self.stdout_trajectory_comparison_result = "DIVERGENT"
            self.stdout_trajectory_comparison_color = COLOR_YELLOW
        else:
            self.stdout_trajectory_comparison_result = "IDENTICAL"
            self.stdout_trajectory_comparison_color = COLOR_GREEN

    def _compute_statistical_verdict(self, **kwargs):
        """Compute statistical comparison verdict."""
        self._compare_statistical_results(**kwargs)
        if not self.different_statistical_results.empty:
            self.statistical_comparison_result = "DIFFERENT"
            self.statistical_comparison_color = COLOR_YELLOW
        else:
            self.statistical_comparison_result = "IDENTICAL"
            self.statistical_comparison_color = COLOR_GREEN

    def _recompute_overall_result(self):
        self.reason = ""
        self.result = "IDENTICAL"
        self.color = COLOR_GREEN
        if self.stdout_trajectory_comparison_result == "DIVERGENT":
            if self.result == "IDENTICAL":
                self.result = "DIVERGENT"
            self.color = COLOR_YELLOW
            self.reason = self.reason + ", different STDOUT trajectories"
        if self.fingerprint_trajectory_comparison_result == "DIVERGENT":
            if self.result == "IDENTICAL":
                self.result = "DIVERGENT"
            self.color = COLOR_YELLOW
            self.reason = self.reason + ", different fingerprint trajectories"
        if self.statistical_comparison_result == "DIFFERENT":
            if self.result == "IDENTICAL":
                self.result = "DIFFERENT"
            self.color = COLOR_YELLOW
            self.reason = self.reason + ", different statistics"
        self.reason = None if self.reason == "" else self.reason[2:]
        self.expected = self.result == "IDENTICAL"

    def debug_at_stdout_divergence_position(self, num_cause_events=0, **kwargs):
        if self.stdout_trajectory_divergence_position:
            event_number_1 = self._get_cause_event_number(self.stdout_trajectory_divergence_position.simulation_event_1, num_cause_events)
            event_number_2 = self._get_cause_event_number(self.stdout_trajectory_divergence_position.simulation_event_2, num_cause_events)
            task_1 = copy.copy(self.multiple_tasks.tasks[0])
            task_1.debug = True
            task_1.mode = "debug"
            task_1.break_at_event_number = event_number_1
            task_2 = copy.copy(self.multiple_tasks.tasks[1])
            task_2.debug = True
            task_2.mode = "debug"
            task_2.break_at_event_number = event_number_2
            multiple_tasks = copy.copy(self.multiple_tasks)
            multiple_tasks.tasks = [task_1, task_2]
            multiple_tasks.run(**kwargs)

    def debug_at_fingerprint_divergence_position(self, num_cause_events=0, **kwargs):
        if self.fingerprint_trajectory_divergence_position:
            event_number_1 = self._get_cause_event_number(self.fingerprint_trajectory_divergence_position.simulation_event_1, num_cause_events)
            event_number_2 = self._get_cause_event_number(self.fingerprint_trajectory_divergence_position.simulation_event_2, num_cause_events)
            task_1 = copy.copy(self.multiple_tasks.tasks[0])
            task_1.debug = True
            task_1.mode = "debug"
            task_1.break_at_event_number = event_number_1
            task_2 = copy.copy(self.multiple_tasks.tasks[1])
            task_2.debug = True
            task_2.mode = "debug"
            task_2.break_at_event_number = event_number_2
            multiple_tasks = copy.copy(self.multiple_tasks)
            multiple_tasks.tasks = [task_1, task_2]
            multiple_tasks.run(**kwargs)

    def run_until_stdout_divergence_position(self, num_cause_events=0, append_args=[], **kwargs):
        if self.stdout_trajectory_divergence_position:
            # NOTE: add 1 to complete the event that causes the fingerprint trajectory divergence
            event_number_1 = self._get_cause_event_number(self.stdout_trajectory_divergence_position.simulation_event_1, num_cause_events) + 1
            event_number_2 = self._get_cause_event_number(self.stdout_trajectory_divergence_position.simulation_event_2, num_cause_events) + 1
            task_1 = copy.copy(self.multiple_tasks.tasks[0])
            task_1.user_interface = "Qtenv"
            task_1.wait = False
            task_1.run(append_args=append_args + [f"-Xev={event_number_1}"], **kwargs)
            task_2 = copy.copy(self.multiple_tasks.tasks[1])
            task_2.user_interface = "Qtenv"
            task_2.wait = False
            task_2.run(append_args=append_args + [f"-Xev={event_number_2}"], **kwargs)

    def run_until_fingerprint_divergence_position(self, num_cause_events=0, append_args=[], **kwargs):
        if self.fingerprint_trajectory_divergence_position:
            # NOTE: add 1 to complete the event that causes the fingerprint trajectory divergence
            event_number_1 = self._get_cause_event_number(self.fingerprint_trajectory_divergence_position.simulation_event_1, num_cause_events) + 1
            event_number_2 = self._get_cause_event_number(self.fingerprint_trajectory_divergence_position.simulation_event_2, num_cause_events) + 1
            task_1 = copy.copy(self.multiple_tasks.tasks[0])
            task_1.user_interface = "Qtenv"
            task_1.wait = False
            task_1.run(append_args=append_args + [f"-Xev={event_number_1}"], **kwargs)
            task_2 = copy.copy(self.multiple_tasks.tasks[1])
            task_2.user_interface = "Qtenv"
            task_2.wait = False
            task_2.run(append_args=append_args + [f"-Xev={event_number_2}"], **kwargs)

    def show_divergence_position_in_sequence_chart(self):
        if self.fingerprint_trajectory_divergence_position:
            self.fingerprint_trajectory_divergence_position.show_in_sequence_chart()

    def print_divergence_position_cause_chain(self, **kwargs):
        if self.fingerprint_trajectory_divergence_position:
            self.fingerprint_trajectory_divergence_position.print_cause_chain(**kwargs)

    def print_different_statistic_modules(self):
        print("\n".join(self.different_statistical_results["module"].unique()))

    def print_different_statistic_names(self):
        print("\n".join(self.different_statistical_results["name"].unique()))

    def print_different_statistical_results(self, drop_columns_with_equals_values=True, include_absolute_errors=False, include_relative_errors=False, include_unbounded_relative_errors=False, **kwargs):
        df = self.different_statistical_results
        if drop_columns_with_equals_values:
            df = df.loc[:, df.nunique() > 1]
        if not include_absolute_errors and "absolute_error" in df.columns:
            df = df.drop("absolute_error", axis=1)
        if not include_relative_errors and "relative_error" in df.columns:
            df = df.drop("relative_error", axis=1)
        if not include_unbounded_relative_errors and "unbounded_relative_error" in df.columns:
            df = df.drop("unbounded_relative_error", axis=1)
        print(df.to_string(index=False, **kwargs))

    def _get_cause_event_number(self, simulation_event, num_cause_events):
        event = simulation_event.get_event()
        if event is None:
            return simulation_event.event_number
        while num_cause_events > 0:
            event = event.getCauseEvent()
            num_cause_events = num_cause_events - 1
        return event.getEventNumber()

    def _find_stdout_trajectory_divergence_position(self, stdout_filter=None, exclude_stdout_filter=None, **kwargs):
        stdout_trajectory_1 = self.multiple_task_results.results[0].get_stdout_trajectory(filter=stdout_filter, exclude_filter=exclude_stdout_filter)
        stdout_trajectory_2 = self.multiple_task_results.results[1].get_stdout_trajectory(filter=stdout_filter, exclude_filter=exclude_stdout_filter)
        return find_stdout_trajectory_divergence_position(stdout_trajectory_1, stdout_trajectory_2)

    def _find_fingerprint_trajectory_divergence_position(self, **kwargs):
        fingerprint_trajectory_1 = self.multiple_task_results.results[0].get_fingerprint_trajectory().get_unique()
        fingerprint_trajectory_2 = self.multiple_task_results.results[1].get_fingerprint_trajectory().get_unique()
        return find_fingerprint_trajectory_divergence_position(fingerprint_trajectory_1, fingerprint_trajectory_2)

    def _compare_statistical_results(self, statistical_result_name_filter=None, exclude_statistic_name_filter=None, statistical_result_module_filter=None, exclude_statistic_module_filter=None, full_match=False, **kwargs):
        self.df_1 = self._get_result_data_frame(self.multiple_task_results.results[0])
        self.df_2 = self._get_result_data_frame(self.multiple_task_results.results[1])
        comparison = compare_scalar_dataframes(self.df_1, self.df_2,
                                               name_filter=statistical_result_name_filter, exclude_name_filter=exclude_statistic_name_filter,
                                               module_filter=statistical_result_module_filter, exclude_module_filter=exclude_statistic_module_filter,
                                               full_match=full_match)
        self.different_statistical_results = comparison.different
        self.identical_statistical_results = comparison.identical

    def _get_result_file_name(self, simulation_task, extension):
        simulation_config = simulation_task.simulation_config
        return f"{simulation_config.ini_file}-{simulation_config.config}-#{simulation_task.run_number}.{extension}"

    def _read_scalar_result_file(self, file_name):
        df = read_result_files(file_name, include_fields_as_scalars=True)
        df = get_scalars(df, include_runattrs=True)
        df = df if df.empty else df[["experiment", "measurement", "replication", "module", "name", "value"]]
        return df

    def _get_result_data_frame(self, simulation_task_result):
        simulation_task = simulation_task_result.task
        simulation_config = simulation_task.simulation_config
        simulation_project = simulation_config.simulation_project
        working_directory = simulation_config.working_directory
        scalar_file_path = simulation_project.get_full_path(os.path.join(working_directory, simulation_task_result.scalar_file_path))
        vector_file_path = simulation_project.get_full_path(os.path.join(working_directory, simulation_task_result.vector_file_path))
        if os.path.exists(vector_file_path):
            run_command_with_logging(["opp_scavetool", "x", "--type", "sth", "-w", vector_file_path, "-o", scalar_file_path])
            os.remove(vector_file_path)
        stored_scalar_result_file_name = simulation_project.get_full_path(os.path.join(simulation_project.statistics_folder, working_directory, simulation_task_result.scalar_file_path))
        _logger.debug(f"Reading result file {scalar_file_path}")
        return self._read_scalar_result_file(scalar_file_path)

class CompareSimulationsTask(Task):
    """Task that runs two simulations and compares the results.

    By default all three comparison axes are enabled.  Pass
    ``compare_stdout=False``, ``compare_fingerprint=False``, or
    ``compare_statistics=False`` to skip individual axes.  The flags
    are stored on the task so they are honoured when the task is re-run.

    Parameters:
        multiple_simulation_tasks:
            A :py:class:`MultipleSimulationTasks` containing exactly two tasks.
        compare_stdout (bool):
            Compare stdout trajectories (default ``True``).
        compare_fingerprint (bool):
            Compare fingerprint trajectories (default ``True``).
        compare_statistics (bool):
            Compare scalar statistical results (default ``True``).
    """

    def __init__(self, multiple_simulation_tasks=None, task_result_class=CompareSimulationsTaskResult, compare_stdout=True, compare_fingerprint=True, compare_statistics=True, name="simulation comparison", **kwargs):
        super().__init__(name=name, task_result_class=task_result_class, **kwargs)
        self.compare_stdout = compare_stdout
        self.compare_fingerprint = compare_fingerprint
        self.compare_statistics = compare_statistics
        self.multiple_simulation_tasks = multiple_simulation_tasks
        num_tasks = len(multiple_simulation_tasks.tasks)
        if num_tasks != 2:
            raise Exception(f"Found {num_tasks} simulation tasks instead of two")
        index = 0
        for task in self.multiple_simulation_tasks.tasks:
            index += 1
            task.record_eventlog = True
            task.stdout_file_path = f"results/{task.simulation_config.config}-#{str(task.run_number)}-{index}.out"
            task.eventlog_file_path = f"results/{task.simulation_config.config}-#{str(task.run_number)}-{index}.elog"
            task.scalar_file_path = f"results/{task.simulation_config.config}-#{str(task.run_number)}-{index}.sca"
            task.vector_file_path = f"results/{task.simulation_config.config}-#{str(task.run_number)}-{index}.vec"
    
    def count_progress_steps(self):
        return 1 + self.multiple_simulation_tasks.count_progress_steps()

    def get_parameters_string(self, **kwargs):
        task_parameters_string_1 = self.multiple_simulation_tasks.tasks[0].get_parameters_string(**kwargs)
        task_parameters_string_2 = self.multiple_simulation_tasks.tasks[1].get_parameters_string(**kwargs)
        if task_parameters_string_1 != task_parameters_string_2:
            return "comparing " + task_parameters_string_1 + " with " + task_parameters_string_2
        else:
            return "comparing " + task_parameters_string_1

    def run_protected(self, context=None, ingredients="tplx", index=None, append_args=[], **kwargs):
        append_args = append_args + ["--cmdenv-express-mode=false", "--cmdenv-log-prefix=%l %C%<: ", "--cmdenv-redirect-output=true", "--eventlog-snapshot-frequency=100MiB", "--eventlog-index-frequency=10MiB", "--eventlog-options=module", "--fingerprint=0000-0000/" + ingredients] + get_ingredients_append_args(ingredients)
        multiple_task_results = self.multiple_simulation_tasks.run(context=context, append_args=append_args, **kwargs)
        return self.task_result_class(multiple_task_results=multiple_task_results, task=self, result=multiple_task_results.result, color=multiple_task_results.color)

class MultipleCompareSimulationsTaskResults(MultipleTaskResults):
    def __init__(self, possible_results=["IDENTICAL", "DIVERGENT", "DIFFERENT", "SKIP", "CANCEL", "ERROR"], possible_result_colors=[COLOR_GREEN, COLOR_YELLOW, COLOR_YELLOW, COLOR_CYAN, COLOR_CYAN, COLOR_RED], **kwargs):
        super().__init__(possible_results=possible_results, possible_result_colors=possible_result_colors, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs

def get_compare_simulations_tasks(multiple_tasks_1, multiple_tasks_2, build=True, **kwargs):
    simulation_comparison_tasks = []
    for task_1, task_2 in zip(multiple_tasks_1.tasks, multiple_tasks_2.tasks):
        simulation_comparison_task = CompareSimulationsTask(multiple_simulation_tasks=MultipleSimulationTasks(tasks=[task_1, task_2], build=False, **kwargs), **kwargs)
        simulation_comparison_tasks.append(simulation_comparison_task)
    if build:
        multiple_tasks_1.build_before_run(**kwargs)
        if multiple_tasks_2.simulation_project is not multiple_tasks_1.simulation_project:
            multiple_tasks_2.build_before_run(**kwargs)
    return MultipleSimulationTasks(tasks=simulation_comparison_tasks, build=False, name="simulation comparison", multiple_task_results_class=MultipleCompareSimulationsTaskResults, **kwargs)
get_compare_simulations_tasks.__signature__ = combine_signatures(get_compare_simulations_tasks, CompareSimulationsTask.__init__, get_simulation_tasks)

def compare_simulations_using_multiple_tasks(multiple_tasks_1, multiple_tasks_2, **kwargs):
    multiple_compare_simulations_tasks = get_compare_simulations_tasks(multiple_tasks_1, multiple_tasks_2, **kwargs)
    return multiple_compare_simulations_tasks.run(**kwargs)

def compare_simulations(**kwargs):
    """Compare simulation results between two projects.

    Use suffixed keyword arguments (``_1`` / ``_2``) for project-specific
    parameters; unsuffixed arguments apply to both sides.  Any keyword
    arguments accepted by :py:func:`get_simulation_tasks` or
    :py:class:`CompareSimulationsTask` can be used.

    Example::

        results = compare_simulations(
            simulation_project_1=project_a,
            simulation_project_2=project_b,
            working_directory_filter="simulations/nr/.*",
            config_filter="General",
            run_number=0)

    Returns:
        :py:class:`MultipleCompareSimulationsTaskResults`
    """
    kwargs_1 = {key[:-2]: value for key, value in kwargs.items() if key.endswith('_1')}
    kwargs_2 = {key[:-2]: value for key, value in kwargs.items() if key.endswith('_2')}
    multiple_simulation_tasks_1 = get_simulation_tasks(**kwargs_1, **kwargs)
    multiple_simulation_tasks_2 = get_simulation_tasks(**kwargs_2, **kwargs)
    return compare_simulations_using_multiple_tasks(multiple_simulation_tasks_1, multiple_simulation_tasks_2, **kwargs)
compare_simulations.__signature__ = combine_signatures(compare_simulations, get_simulation_tasks)

def compare_simulations_between_commits(simulation_project, git_hash_1, git_hash_2, **kwargs):
    """Compare simulation results between two git versions of the same project.

    Creates git worktrees for each commit, builds both, and runs the
    comparison pipeline.

    Parameters:
        simulation_project (:py:class:`SimulationProject`):
            The simulation project whose repository contains both commits.
        git_hash_1 (str):
            First git commit-ish (hash, tag, branch, etc.).
        git_hash_2 (str):
            Second git commit-ish.
        kwargs:
            Forwarded to :py:func:`compare_simulations`.

    Returns:
        The result of :py:func:`compare_simulations_using_multiple_tasks`.
    """
    from opp_repl.simulation.project import make_worktree_simulation_project
    project_1 = make_worktree_simulation_project(simulation_project, git_hash_1)
    project_2 = make_worktree_simulation_project(simulation_project, git_hash_2)
    return compare_simulations(simulation_project_1=project_1, simulation_project_2=project_2, **kwargs)
compare_simulations_between_commits.__signature__ = combine_signatures(compare_simulations_between_commits, compare_simulations)

def compare_statistics(**kwargs):
    """Compare only statistical (scalar) results between two projects.

    Thin wrapper around :py:func:`compare_simulations` with stdout and
    fingerprint comparison disabled.

    Example::

        results = compare_statistics(
            simulation_project_1=project_a,
            simulation_project_2=project_b,
            working_directory_filter="examples/ethernet",
            config_filter="General",
            run_number=0)

    Returns:
        :py:class:`MultipleCompareSimulationsTaskResults`
    """
    return compare_simulations(compare_stdout=False, compare_fingerprint=False, **kwargs)
compare_statistics.__signature__ = combine_signatures(compare_statistics, compare_simulations)

def compare_statistics_between_commits(simulation_project, git_hash_1, git_hash_2, **kwargs):
    """Compare only statistical results between two git versions.

    Thin wrapper around :py:func:`compare_simulations_between_commits` with
    stdout and fingerprint comparison disabled.

    Parameters:
        simulation_project: The project whose repository contains both commits.
        git_hash_1 (str): First git commit-ish.
        git_hash_2 (str): Second git commit-ish.

    Returns:
        The result of :py:func:`compare_simulations_between_commits`.
    """
    return compare_simulations_between_commits(simulation_project, git_hash_1, git_hash_2, compare_stdout=False, compare_fingerprint=False, **kwargs)
compare_statistics_between_commits.__signature__ = combine_signatures(compare_statistics_between_commits, compare_simulations_between_commits)

def compare_stdout(**kwargs):
    """Compare only stdout trajectories between two projects.

    Thin wrapper around :py:func:`compare_simulations` with fingerprint and
    statistics comparison disabled.

    Returns:
        :py:class:`MultipleCompareSimulationsTaskResults`
    """
    return compare_simulations(compare_fingerprint=False, compare_statistics=False, **kwargs)
compare_stdout.__signature__ = combine_signatures(compare_stdout, compare_simulations)

def compare_stdout_between_commits(simulation_project, git_hash_1, git_hash_2, **kwargs):
    """Compare only stdout trajectories between two git versions.

    Thin wrapper around :py:func:`compare_simulations_between_commits` with
    fingerprint and statistics comparison disabled.

    Parameters:
        simulation_project: The project whose repository contains both commits.
        git_hash_1 (str): First git commit-ish.
        git_hash_2 (str): Second git commit-ish.

    Returns:
        The result of :py:func:`compare_simulations_between_commits`.
    """
    return compare_simulations_between_commits(simulation_project, git_hash_1, git_hash_2, compare_fingerprint=False, compare_statistics=False, **kwargs)
compare_stdout_between_commits.__signature__ = combine_signatures(compare_stdout_between_commits, compare_simulations_between_commits)

def compare_fingerprints(**kwargs):
    """Compare only fingerprint trajectories between two projects.

    Thin wrapper around :py:func:`compare_simulations` with stdout and
    statistics comparison disabled.

    Returns:
        :py:class:`MultipleCompareSimulationsTaskResults`
    """
    return compare_simulations(compare_stdout=False, compare_statistics=False, **kwargs)
compare_fingerprints.__signature__ = combine_signatures(compare_fingerprints, compare_simulations)

def compare_fingerprints_between_commits(simulation_project, git_hash_1, git_hash_2, **kwargs):
    """Compare only fingerprint trajectories between two git versions.

    Thin wrapper around :py:func:`compare_simulations_between_commits` with
    stdout and statistics comparison disabled.

    Parameters:
        simulation_project: The project whose repository contains both commits.
        git_hash_1 (str): First git commit-ish.
        git_hash_2 (str): Second git commit-ish.

    Returns:
        The result of :py:func:`compare_simulations_between_commits`.
    """
    return compare_simulations_between_commits(simulation_project, git_hash_1, git_hash_2, compare_stdout=False, compare_statistics=False, **kwargs)
compare_fingerprints_between_commits.__signature__ = combine_signatures(compare_fingerprints_between_commits, compare_simulations_between_commits)

def compare_charts(**kwargs):
    """Compare chart images between two projects.

    Not yet implemented.
    """
    raise NotImplementedError("compare_charts is not yet implemented")

def compare_charts_between_commits(simulation_project, git_hash_1, git_hash_2, **kwargs):
    """Compare chart images between two git versions.

    Not yet implemented.
    """
    raise NotImplementedError("compare_charts_between_commits is not yet implemented")

def compare_speed(**kwargs):
    """Compare simulation speed (CPU instruction counts) between two projects.

    Not yet implemented.
    """
    raise NotImplementedError("compare_speed is not yet implemented")

def compare_speed_between_commits(simulation_project, git_hash_1, git_hash_2, **kwargs):
    """Compare simulation speed between two git versions.

    Not yet implemented.
    """
    raise NotImplementedError("compare_speed_between_commits is not yet implemented")
