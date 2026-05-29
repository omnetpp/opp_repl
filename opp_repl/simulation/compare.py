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
import tempfile

import pandas as pd

try:
    from omnetpp.scave.results import *
except (ImportError, ModuleNotFoundError):
    pass

from opp_repl.common.util import *
from opp_repl.simulation.displaystring import *
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

            if self.task.compare_eventlog:
                self._compute_eventlog_verdict(**self.multiple_tasks.kwargs)
            else:
                self.eventlog_divergence_position = None
                self.eventlog_comparison_result = None
                self.eventlog_comparison_color = None

            if self.task.compare_statistics:
                self._compute_statistical_verdict(**self.multiple_tasks.kwargs)
            else:
                self.different_statistical_results = pd.DataFrame()
                self.only_1_statistical_results = pd.DataFrame()
                self.only_2_statistical_results = pd.DataFrame()
                self.statistical_comparison_result = None
                self.statistical_comparison_color = None

            # Chart verdicts are computed by _finalize_chart_comparisons after
            # all simulations finish — a single chart can aggregate over many
            # runs, so rendering must wait until every sim has populated the
            # result folder. Left as a no-op verdict here; the post-pass fills
            # it in and re-runs _recompute_overall_result.
            self.chart_comparison_result = None
            self.chart_comparison_color = None
            self.different_chart_files = []

            # Module-image verdicts are computed by
            # _finalize_module_image_comparisons after all simulations finish —
            # module-image capture requires a Qtenv MCP launch separate from
            # the Cmdenv simulation runs, so it runs as a post-pass.
            self.module_image_comparison_result = None
            self.module_image_comparison_color = None
            self.different_module_image_files = []

            self._recompute_overall_result()
        else:
            self.stdout_trajectory_divergence_position = None
            self.stdout_trajectory_comparison_result = None
            self.stdout_trajectory_comparison_color = None
            self.fingerprint_trajectory_divergence_position = None
            self.fingerprint_trajectory_comparison_result = None
            self.fingerprint_trajectory_comparison_color = None
            self.eventlog_divergence_position = None
            self.eventlog_comparison_result = None
            self.eventlog_comparison_color = None
            self.different_statistical_results = pd.DataFrame()
            self.only_1_statistical_results = pd.DataFrame()
            self.only_2_statistical_results = pd.DataFrame()
            self.statistical_comparison_result = None
            self.statistical_comparison_color = None
            self.chart_comparison_result = None
            self.chart_comparison_color = None
            self.different_chart_files = []
            self.module_image_comparison_result = None
            self.module_image_comparison_color = None
            self.different_module_image_files = []
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
        if self.eventlog_divergence_position:
            eventlog_divergence_description = f"\nEventlog comparison result: {self.eventlog_comparison_color}{self.eventlog_comparison_result}{COLOR_RESET}\n{self.eventlog_divergence_position.get_description()}"
        elif self.eventlog_comparison_result:
            eventlog_divergence_description = f"\nEventlog comparison result: {self.eventlog_comparison_color}{self.eventlog_comparison_result}{COLOR_RESET}"
        else:
            eventlog_divergence_description = ""
        if not self.different_statistical_results.empty or not self.only_1_statistical_results.empty or not self.only_2_statistical_results.empty:
            max_num_different_statistics = 3
            summary_parts = [f"{COLOR_GREEN}{str(len(self.identical_statistical_results))} IDENTICAL{COLOR_RESET}"]
            if not self.only_1_statistical_results.empty:
                summary_parts.append(f"{COLOR_YELLOW}{str(len(self.only_1_statistical_results))} ONLY_1{COLOR_RESET}")
            if not self.only_2_statistical_results.empty:
                summary_parts.append(f"{COLOR_YELLOW}{str(len(self.only_2_statistical_results))} ONLY_2{COLOR_RESET}")
            if not self.different_statistical_results.empty:
                summary_parts.append(f"{COLOR_YELLOW}{str(len(self.different_statistical_results))} DIFFERENT{COLOR_RESET}")
            summary_str = ", ".join(summary_parts)
            detail_str = ""
            if not self.different_statistical_results.empty:
                different_unique_modules = self.different_statistical_results["module"].unique()
                different_unique_statistics = self.different_statistical_results["name"].unique()
                different_modules = ", ".join(map(lambda s: f"{COLOR_CYAN}{s}{COLOR_RESET}", different_unique_modules[0:max_num_different_statistics])) + (", ..." if len(different_unique_modules) > max_num_different_statistics else "")
                different_statistics = ", ".join(map(lambda s: f"{COLOR_GREEN}{s}{COLOR_RESET}", different_unique_statistics[0:max_num_different_statistics])) + (", ..." if len(different_unique_statistics) > max_num_different_statistics else "")
                detail_str = f", some differences: {different_statistics} in {different_modules}"
            statistical_desription = f"\nStatistical comparison result: {self.statistical_comparison_color}{self.statistical_comparison_result}{COLOR_RESET}, summary: {summary_str}{detail_str}"
        elif self.statistical_comparison_result:
            statistical_desription = f"\nStatistical comparison result: {self.statistical_comparison_color}{self.statistical_comparison_result}{COLOR_RESET}"
        else:
            statistical_desription = ""
        if self.different_chart_files:
            chart_description = f"\nChart comparison result: {self.chart_comparison_color}{self.chart_comparison_result}{COLOR_RESET}, {len(self.different_chart_files)} differing chart(s)"
        elif self.chart_comparison_result:
            chart_description = f"\nChart comparison result: {self.chart_comparison_color}{self.chart_comparison_result}{COLOR_RESET}"
        else:
            chart_description = ""
        if self.different_module_image_files:
            module_image_description = f"\nModule image comparison result: {self.module_image_comparison_color}{self.module_image_comparison_result}{COLOR_RESET}, {len(self.different_module_image_files)} differing image(s)"
        elif self.module_image_comparison_result:
            module_image_description = f"\nModule image comparison result: {self.module_image_comparison_color}{self.module_image_comparison_result}{COLOR_RESET}"
        else:
            module_image_description = ""
        return TaskResult.__repr__(self) + "\n" + stdout_trajectory_divergence_description + fingerprint_trajectory_divergence_description + eventlog_divergence_description + statistical_desription + chart_description + module_image_description

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
            result_name_filter (str or None): Regex for scalar names (applied to *different* rows).
            exclude_result_name_filter (str or None): Regex to exclude scalar names from *different*.
            result_module_filter (str or None): Regex for modules (applied to *different* rows).
            exclude_result_module_filter (str or None): Regex to exclude modules from *different*.
            only_result_name_filter (str or None): Regex applied to only-side rows; non-matching
                rows are dropped from ``only_1_statistical_results``/``only_2_statistical_results``.
            exclude_only_result_name_filter (str or None): Exclude-side of ``only_result_name_filter``.
            only_result_module_filter (str or None): Module regex for only-side rows.
            exclude_only_result_module_filter (str or None): Exclude-side of ``only_result_module_filter``.
            rename_1 (callable or None): ``(module, name) -> (module, name)`` rewriting df_1 keys
                before the merge so renamed statistics line up.  Not persisted across calls.
            rename_2 (callable or None): Same as ``rename_1`` but for df_2.
            full_match (bool): Use ``re.fullmatch`` instead of ``re.search``.

        Returns:
            CompareSimulationsTaskResult: A new result with updated verdicts.
        """
        import copy
        new_result = copy.copy(self)
        if self.task.compare_stdout:
            new_result._compute_stdout_verdict(**kwargs)
        if self.task.compare_eventlog:
            new_result._compute_eventlog_verdict(**kwargs)
        if self.task.compare_statistics:
            new_result._compute_statistical_verdict(**kwargs)
        if self.task.compare_charts:
            new_result._compute_chart_verdict()
        if self.task.compare_module_images:
            new_result._compute_module_image_verdict()
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

    def _compute_eventlog_verdict(self, eventlog_filter=None, exclude_eventlog_filter=None, **kwargs):
        """Compute eventlog comparison verdict."""
        from opp_repl.simulation.displaystring import read_eventlog_lines, find_eventlog_divergence_position
        event_numbers_1, lines_1 = read_eventlog_lines(self.multiple_task_results.results[0], filter=eventlog_filter, exclude_filter=exclude_eventlog_filter)
        event_numbers_2, lines_2 = read_eventlog_lines(self.multiple_task_results.results[1], filter=eventlog_filter, exclude_filter=exclude_eventlog_filter)
        self.eventlog_divergence_position = find_eventlog_divergence_position(
            event_numbers_1, lines_1, event_numbers_2, lines_2,
            self.multiple_task_results.results[0], self.multiple_task_results.results[1])
        if self.eventlog_divergence_position:
            self.eventlog_comparison_result = "DIVERGENT"
            self.eventlog_comparison_color = COLOR_YELLOW
        else:
            self.eventlog_comparison_result = "IDENTICAL"
            self.eventlog_comparison_color = COLOR_GREEN

    def _compute_statistical_verdict(self, **kwargs):
        """Compute statistical comparison verdict."""
        self._compare_statistical_results(**kwargs)
        if not self.different_statistical_results.empty or not self.only_1_statistical_results.empty or not self.only_2_statistical_results.empty:
            self.statistical_comparison_result = "DIFFERENT"
            self.statistical_comparison_color = COLOR_YELLOW
        else:
            self.statistical_comparison_result = "IDENTICAL"
            self.statistical_comparison_color = COLOR_GREEN

    def _compute_chart_verdict(self):
        """Compute chart comparison verdict by scanning the task's staging subdir
        for non-empty ``-diff.png`` files produced by ``_render_and_diff_charts``."""
        self.different_chart_files = []
        staging_dir = getattr(self.task, "staging_dir", None)
        if not staging_dir:
            self.chart_comparison_result = None
            self.chart_comparison_color = None
            return
        working_directory = self.task.multiple_simulation_tasks.tasks[0].simulation_config.working_directory
        scope = os.path.join(staging_dir, working_directory)
        if os.path.isdir(scope):
            for dirpath, _dirs, files in os.walk(scope):
                for fname in files:
                    if fname.endswith("-diff.png"):
                        self.different_chart_files.append(os.path.join(dirpath, fname))
        if self.different_chart_files:
            self.chart_comparison_result = "DIFFERENT"
            self.chart_comparison_color = COLOR_YELLOW
        else:
            self.chart_comparison_result = "IDENTICAL"
            self.chart_comparison_color = COLOR_GREEN

    def open_charts_in_gui(self):
        """Open the chart staging directory for this task's working directory
        in the :command:`opp_diff_charts` GUI (non-blocking)."""
        staging_dir = getattr(self.task, "staging_dir", None)
        if not staging_dir:
            raise RuntimeError("No chart staging directory; re-run with compare_charts=True")
        return _launch_diffcharts_gui(staging_dir)

    def _compute_module_image_verdict(self):
        """Compute module-image comparison verdict by scanning the task's
        staging subdir for non-empty ``-diff.png`` files produced by
        ``_finalize_module_image_comparisons``."""
        self.different_module_image_files = []
        staging_dir = getattr(self.task, "staging_dir", None)
        if not staging_dir:
            self.module_image_comparison_result = None
            self.module_image_comparison_color = None
            return
        working_directory = self.task.multiple_simulation_tasks.tasks[0].simulation_config.working_directory
        scope = os.path.join(staging_dir, working_directory, "module_images")
        if os.path.isdir(scope):
            for fname in sorted(os.listdir(scope)):
                if fname.endswith("-diff.png"):
                    self.different_module_image_files.append(os.path.join(scope, fname))
        if self.different_module_image_files:
            self.module_image_comparison_result = "DIFFERENT"
            self.module_image_comparison_color = COLOR_YELLOW
        else:
            self.module_image_comparison_result = "IDENTICAL"
            self.module_image_comparison_color = COLOR_GREEN

    def open_module_images_in_gui(self):
        """Open the module-image staging directory in the
        :command:`opp_diff_charts` GUI (non-blocking).

        Reuses the chart-diff GUI since the file layout (``-old.png`` /
        ``-new.png`` / ``-diff.png`` triples) is identical.
        """
        staging_dir = getattr(self.task, "staging_dir", None)
        if not staging_dir:
            raise RuntimeError("No module-image staging directory; re-run with compare_module_images=True")
        working_directory = self.task.multiple_simulation_tasks.tasks[0].simulation_config.working_directory
        scope = os.path.join(staging_dir, working_directory, "module_images")
        return _launch_diffcharts_gui(scope)

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
        if self.eventlog_comparison_result == "DIVERGENT":
            if self.result == "IDENTICAL":
                self.result = "DIVERGENT"
            self.color = COLOR_YELLOW
            self.reason = self.reason + ", different eventlogs"
        if self.statistical_comparison_result == "DIFFERENT":
            if self.result == "IDENTICAL":
                self.result = "DIFFERENT"
            self.color = COLOR_YELLOW
            self.reason = self.reason + ", different statistics"
        if self.chart_comparison_result == "DIFFERENT":
            if self.result == "IDENTICAL":
                self.result = "DIFFERENT"
            self.color = COLOR_YELLOW
            self.reason = self.reason + ", different charts"
        if self.module_image_comparison_result == "DIFFERENT":
            if self.result == "IDENTICAL":
                self.result = "DIFFERENT"
            self.color = COLOR_YELLOW
            self.reason = self.reason + ", different module images"
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
            # The original compare built whatever mode it ran in (e.g. release);
            # switching to debug here requires a debug build. Each task builds
            # its own simulation_project so cross-commit compares still work
            # — make is incremental so the same-project case is cheap.
            task_1.build = True
            task_2 = copy.copy(self.multiple_tasks.tasks[1])
            task_2.debug = True
            task_2.mode = "debug"
            task_2.break_at_event_number = event_number_2
            task_2.build = True
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
            task_1.build = True
            task_2 = copy.copy(self.multiple_tasks.tasks[1])
            task_2.debug = True
            task_2.mode = "debug"
            task_2.break_at_event_number = event_number_2
            task_2.build = True
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
            # Switching to Qtenv requires a build of the Qtenv-linked executable.
            # The original compare built Cmdenv only, so force a build per task —
            # make is incremental, so when both tasks share a project the second
            # invocation is a near no-op; when they don't (cross-commit compare)
            # each project does need its own build.
            task_1.build = True
            task_1.run(append_args=append_args + [f"-Xev={event_number_1}"], **kwargs)
            task_2 = copy.copy(self.multiple_tasks.tasks[1])
            task_2.user_interface = "Qtenv"
            task_2.wait = False
            task_2.build = True
            task_2.run(append_args=append_args + [f"-Xev={event_number_2}"], **kwargs)

    def run_until_fingerprint_divergence_position(self, num_cause_events=0, append_args=[], **kwargs):
        if self.fingerprint_trajectory_divergence_position:
            # NOTE: add 1 to complete the event that causes the fingerprint trajectory divergence
            event_number_1 = self._get_cause_event_number(self.fingerprint_trajectory_divergence_position.simulation_event_1, num_cause_events) + 1
            event_number_2 = self._get_cause_event_number(self.fingerprint_trajectory_divergence_position.simulation_event_2, num_cause_events) + 1
            task_1 = copy.copy(self.multiple_tasks.tasks[0])
            task_1.user_interface = "Qtenv"
            task_1.wait = False
            task_1.build = True
            task_1.run(append_args=append_args + [f"-Xev={event_number_1}"], **kwargs)
            task_2 = copy.copy(self.multiple_tasks.tasks[1])
            task_2.user_interface = "Qtenv"
            task_2.wait = False
            task_2.build = True
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

    def _compare_statistical_results(self,
                                      result_name_filter=None, exclude_result_name_filter=None,
                                      result_module_filter=None, exclude_result_module_filter=None,
                                      only_result_name_filter=None, exclude_only_result_name_filter=None,
                                      only_result_module_filter=None, exclude_only_result_module_filter=None,
                                      rename_1=None, rename_2=None,
                                      full_match=False, **kwargs):
        self.df_1 = self._get_result_data_frame(self.multiple_task_results.results[0])
        self.df_2 = self._get_result_data_frame(self.multiple_task_results.results[1])
        comparison = compare_scalar_dataframes(self.df_1, self.df_2,
                                               name_filter=result_name_filter, exclude_name_filter=exclude_result_name_filter,
                                               module_filter=result_module_filter, exclude_module_filter=exclude_result_module_filter,
                                               only_name_filter=only_result_name_filter, exclude_only_name_filter=exclude_only_result_name_filter,
                                               only_module_filter=only_result_module_filter, exclude_only_module_filter=exclude_only_result_module_filter,
                                               rename_1=rename_1, rename_2=rename_2,
                                               full_match=full_match)
        self.statistical_comparison = comparison
        self.different_statistical_results = comparison.different
        self.identical_statistical_results = comparison.identical
        self.only_1_statistical_results = comparison.only_1
        self.only_2_statistical_results = comparison.only_2

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

    By default the stdout, fingerprint, and statistics axes are enabled and
    the (heavier) chart and module-image axes are disabled.  Pass
    ``compare_stdout=False``, ``compare_fingerprint=False``,
    ``compare_statistics=False``, ``compare_charts=True``, or
    ``compare_module_images=True`` to override.  The flags are stored on the
    task so they are honoured when the task is re-run.

    Parameters:
        multiple_simulation_tasks:
            A :py:class:`MultipleSimulationTasks` containing exactly two tasks.
        compare_stdout (bool):
            Compare stdout trajectories (default ``True``).
        compare_fingerprint (bool):
            Compare fingerprint trajectories (default ``True``).
        compare_statistics (bool):
            Compare scalar statistical results (default ``True``).
        compare_charts (bool):
            Render every chart from every matching ``.anf`` file in each
            side's working directory and compute pixel diffs (default
            ``False``).  Requires *staging_dir*.
        compare_module_images (bool):
            Launch each side's simulation a second time in Qtenv with its
            MCP server enabled, capture a PNG of every compound module that
            matches the include/exclude filters, and compute pixel diffs
            (default ``False``).  Requires *staging_dir*.
        staging_dir (str | None):
            Where the per-task chart and module-image PNGs are written.  Set
            by :py:func:`get_compare_simulations_tasks` when
            ``compare_charts=True`` or ``compare_module_images=True``.
        chart_filter / exclude_chart_filter (str | None):
            Regex applied to chart names when ``compare_charts=True``.
        module_path_filter / exclude_module_path_filter (str | None):
            Glob applied to module full paths when
            ``compare_module_images=True``.
        module_type_filter / exclude_module_type_filter (str | None):
            Glob applied to module NED types when
            ``compare_module_images=True``.
        group_by (str):
            ``"path"`` (default), ``"type"``, or ``"path_no_indices"``.
            Forwarded to :py:func:`capture_module_images`.
        area (str):
            ``"all_elements"`` (default), ``"module_rectangle"``, or
            ``"viewport"``.  Forwarded to ``get_canvas_image``.
        margin (int):
            Pixel margin around the captured area (default 5).
        startup_timeout (float):
            Seconds to wait for each module-image simulation's MCP endpoint
            (default 30).
    """

    def __init__(self, multiple_simulation_tasks=None, task_result_class=CompareSimulationsTaskResult,
                 compare_stdout=True, compare_fingerprint=True, compare_statistics=True,
                 compare_eventlog=False,
                 compare_charts=False, compare_module_images=False, staging_dir=None,
                 chart_filter=None, exclude_chart_filter=None,
                 module_path_filter=None, exclude_module_path_filter=None,
                 module_type_filter=None, exclude_module_type_filter=None,
                 group_by="path", area="all_elements", margin=5, startup_timeout=30.0,
                 eventlog_options=None,
                 name="simulation comparison", **kwargs):
        super().__init__(name=name, task_result_class=task_result_class, **kwargs)
        self.compare_stdout = compare_stdout
        self.compare_fingerprint = compare_fingerprint
        self.compare_statistics = compare_statistics
        self.compare_eventlog = compare_eventlog
        self.compare_charts = compare_charts
        self.compare_module_images = compare_module_images
        self.staging_dir = staging_dir
        self.chart_filter = chart_filter
        self.exclude_chart_filter = exclude_chart_filter
        self.module_path_filter = module_path_filter
        self.exclude_module_path_filter = exclude_module_path_filter
        self.module_type_filter = module_type_filter
        self.exclude_module_type_filter = exclude_module_type_filter
        self.group_by = group_by
        self.area = area
        self.margin = margin
        self.startup_timeout = startup_timeout
        if eventlog_options is None:
            self.eventlog_options = "module" if not compare_eventlog else ""
        else:
            self.eventlog_options = eventlog_options
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
        eventlog_options_args = ["--eventlog-options=" + self.eventlog_options] if self.eventlog_options else []
        append_args = append_args + ["--cmdenv-express-mode=false", "--cmdenv-log-prefix=%l %C%<: ", "--cmdenv-redirect-output=true", "--eventlog-snapshot-frequency=100MiB", "--eventlog-index-frequency=10MiB"] + eventlog_options_args + ["--fingerprint=0000-0000/" + ingredients] + get_ingredients_append_args(ingredients)
        multiple_task_results = self.multiple_simulation_tasks.run(context=context, append_args=append_args, **kwargs)
        return self.task_result_class(multiple_task_results=multiple_task_results, task=self, result=multiple_task_results.result, color=multiple_task_results.color)

class MultipleCompareSimulationsTaskResults(MultipleTaskResults):
    def __init__(self, possible_results=["IDENTICAL", "DIVERGENT", "DIFFERENT", "SKIP", "CANCEL", "ERROR"], possible_result_colors=[COLOR_GREEN, COLOR_YELLOW, COLOR_YELLOW, COLOR_CYAN, COLOR_CYAN, COLOR_RED], **kwargs):
        super().__init__(possible_results=possible_results, possible_result_colors=possible_result_colors, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs

    @property
    def staging_dir(self):
        """The shared chart staging directory, or ``None`` if ``compare_charts``
        was not enabled for this comparison."""
        return getattr(self.multiple_tasks, "staging_dir", None) if self.multiple_tasks else None

    def open_charts_in_gui(self):
        """Open the chart staging directory in the :command:`opp_diff_charts` GUI.

        Returns the spawned :class:`subprocess.Popen` handle (non-blocking).
        Raises :class:`RuntimeError` if charts were not rendered (i.e. the
        comparison was run with ``compare_charts=False``).
        """
        if not self.staging_dir:
            raise RuntimeError("No chart staging directory available; "
                               "re-run with compare_charts=True")
        return _launch_diffcharts_gui(self.staging_dir)

def get_compare_simulations_tasks(multiple_tasks_1, multiple_tasks_2, build=True,
                                  compare_charts=False, compare_module_images=False,
                                  staging_dir=None, **kwargs):
    if (compare_charts or compare_module_images) and staging_dir is None:
        staging_dir = tempfile.mkdtemp(prefix="opp_diff_charts_")
    simulation_comparison_tasks = []
    for task_1, task_2 in zip(multiple_tasks_1.tasks, multiple_tasks_2.tasks):
        simulation_comparison_task = CompareSimulationsTask(
            multiple_simulation_tasks=MultipleSimulationTasks(tasks=[task_1, task_2], build=False, **kwargs),
            compare_charts=compare_charts, compare_module_images=compare_module_images,
            staging_dir=staging_dir, **kwargs)
        simulation_comparison_tasks.append(simulation_comparison_task)
    if build:
        multiple_tasks_1.build_before_run(**kwargs)
        if multiple_tasks_2.simulation_project is not multiple_tasks_1.simulation_project:
            multiple_tasks_2.build_before_run(**kwargs)
    aggregate = MultipleSimulationTasks(tasks=simulation_comparison_tasks, build=False, name="simulation comparison", multiple_task_results_class=MultipleCompareSimulationsTaskResults, **kwargs)
    aggregate.staging_dir = staging_dir
    return aggregate
get_compare_simulations_tasks.__signature__ = combine_signatures(get_compare_simulations_tasks, CompareSimulationsTask.__init__, get_simulation_tasks)

def compare_simulations_using_multiple_tasks(multiple_tasks_1, multiple_tasks_2, **kwargs):
    multiple_compare_simulations_tasks = get_compare_simulations_tasks(multiple_tasks_1, multiple_tasks_2, **kwargs)
    results = multiple_compare_simulations_tasks.run(**kwargs)
    _finalize_chart_comparisons(multiple_compare_simulations_tasks.tasks, results)
    _finalize_module_image_comparisons(multiple_compare_simulations_tasks.tasks, results)
    return results

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
compare_simulations.__signature__ = combine_signatures(compare_simulations, get_simulation_tasks, CompareSimulationsTask.__init__)

def compare_simulations_between_commits(simulation_project=None, git_hash_1=None, git_hash_2=None, delete_worktree=False, **kwargs):
    """Compare simulation results between two git versions of the same project.

    Creates git worktrees for each commit, builds both, and runs the
    comparison pipeline.

    Parameters:
        simulation_project (:py:class:`SimulationProject`):
            The simulation project whose repository contains both commits.
            If ``None``, the default simulation project is used.
        git_hash_1 (str):
            First git commit-ish (hash, tag, branch, etc.).
        git_hash_2 (str):
            Second git commit-ish.
        delete_worktree (bool):
            If ``True``, the git worktrees created for the two commits are
            removed after the comparison finishes (including on error).
            Default ``False`` (worktrees are kept for reuse).
        kwargs:
            Forwarded to :py:func:`compare_simulations`.

    Returns:
        The result of :py:func:`compare_simulations_using_multiple_tasks`.
    """
    from opp_repl.simulation.project import make_worktree_simulation_project, remove_worktree_simulation_project
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    project_1 = make_worktree_simulation_project(simulation_project, git_hash_1)
    project_2 = make_worktree_simulation_project(simulation_project, git_hash_2)
    try:
        return compare_simulations(simulation_project_1=project_1, simulation_project_2=project_2, **kwargs)
    finally:
        if delete_worktree:
            remove_worktree_simulation_project(project_1)
            if project_2.get_root_path() != project_1.get_root_path():
                remove_worktree_simulation_project(project_2)
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

def compare_statistics_between_commits(**kwargs):
    """Compare only statistical results between two git versions.

    Thin wrapper around :py:func:`compare_simulations_between_commits` with
    stdout and fingerprint comparison disabled.

    Returns:
        The result of :py:func:`compare_simulations_between_commits`.
    """
    return compare_simulations_between_commits(compare_stdout=False, compare_fingerprint=False, **kwargs)
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

def compare_stdout_between_commits(**kwargs):
    """Compare only stdout trajectories between two git versions.

    Thin wrapper around :py:func:`compare_simulations_between_commits` with
    fingerprint and statistics comparison disabled.

    Returns:
        The result of :py:func:`compare_simulations_between_commits`.
    """
    return compare_simulations_between_commits(compare_fingerprint=False, compare_statistics=False, **kwargs)
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

def compare_fingerprints_between_commits(**kwargs):
    """Compare only fingerprint trajectories between two git versions.

    Thin wrapper around :py:func:`compare_simulations_between_commits` with
    stdout and statistics comparison disabled.

    Returns:
        The result of :py:func:`compare_simulations_between_commits`.
    """
    return compare_simulations_between_commits(compare_stdout=False, compare_statistics=False, **kwargs)
compare_fingerprints_between_commits.__signature__ = combine_signatures(compare_fingerprints_between_commits, compare_simulations_between_commits)

def _resolve_commit_list(simulation_project, commits):
    """Resolve *commits* into an ordered list of commit-ishes (oldest → newest).

    *commits* is either a list of commit-ishes (used as-is) or a string
    holding a git revision range such as ``"v1.0..HEAD"`` (resolved via
    ``git rev-list --reverse --first-parent``).
    """
    if commits is None:
        raise ValueError("'commits' must be a list of commit-ishes or a revision-range string")
    if isinstance(commits, str):
        # --reverse → chronological; --first-parent keeps merges sane on a mainline.
        result = run_command_with_logging(
            ["git", "-C", simulation_project.get_full_path("."),
             "rev-list", "--reverse", "--first-parent", commits],
            error_message=f"Failed to resolve commit range {commits!r}")
        commits = result.stdout.strip().splitlines()
    if len(commits) < 2:
        raise ValueError(f"Need at least two commits to compare, got {len(commits)}")
    return commits

def _build_commit_pairs(commits, comparison_mode):
    """Build (hash_1, hash_2) pairs from *commits* according to *comparison_mode*."""
    if comparison_mode == "differential":
        return list(zip(commits[:-1], commits[1:]))     # (c0,c1), (c1,c2), ...
    if comparison_mode == "baseline":
        return [(commits[0], c) for c in commits[1:]]   # (c0,c1), (c0,c2), ...
    raise ValueError(f"Unknown comparison_mode: {comparison_mode!r} "
                     f"(expected 'differential' or 'baseline')")

def compare_simulations_across_commits(simulation_project=None, commits=None,
                                       comparison_mode="differential", delete_worktree=False, **kwargs):
    """Compare simulation results across a sequence of git commits.

    Two comparison modes are supported:

    * ``"differential"`` — compare each commit against its predecessor:
      ``(c[0], c[1]), (c[1], c[2]), ..., (c[N-2], c[N-1])``.  Useful for
      walking history one step at a time to locate the change that
      introduced a regression.

    * ``"baseline"`` — compare every later commit against the first one:
      ``(c[0], c[1]), (c[0], c[2]), ..., (c[0], c[N-1])``.  Useful for
      tracking cumulative drift from a reference point.

    Each unique commit is checked out in a git worktree at most once, so
    baseline mode does not rebuild the reference commit repeatedly.

    Parameters:
        simulation_project (:py:class:`SimulationProject`):
            The project whose repository contains the commits.  If ``None``,
            the default simulation project is used.
        commits (list[str] | str):
            Either a list of commit-ishes (oldest → newest) or a string
            holding a git revision range such as ``"v1.0..HEAD"``.  Ranges
            are resolved with ``git rev-list --reverse --first-parent``.
        comparison_mode (str):
            ``"differential"`` (default) or ``"baseline"``.
        delete_worktree (bool):
            If ``True``, every worktree created by this call is removed
            after the comparison finishes (including on error).  Default
            ``False`` (worktrees are kept for reuse).
        kwargs:
            Forwarded to :py:func:`compare_simulations` / :py:class:`CompareSimulationsTask`.

    Returns:
        :py:class:`MultipleCompareSimulationsTaskResults` — one result per
        (pair, config) combination, flattened.  Each task is named with the
        short hashes of the pair so results are identifiable.
    """
    from opp_repl.simulation.project import make_worktree_simulation_project, remove_worktree_simulation_project
    if simulation_project is None:
        simulation_project = get_default_simulation_project()

    commits = _resolve_commit_list(simulation_project, commits)
    pairs = _build_commit_pairs(commits, comparison_mode)

    project_cache = {}
    def project_for(commit):
        if commit not in project_cache:
            project_cache[commit] = make_worktree_simulation_project(simulation_project, commit)
        return project_cache[commit]

    # Per the compare_simulations convention, _1 / _2 suffixed kwargs are
    # side-specific. Strip a user-supplied simulation_project_{1,2} so it
    # cannot collide with the worktree projects we inject below.
    kwargs_1 = {k[:-2]: v for k, v in kwargs.items() if k.endswith('_1')}
    kwargs_2 = {k[:-2]: v for k, v in kwargs.items() if k.endswith('_2')}
    kwargs_1.pop("simulation_project", None)
    kwargs_2.pop("simulation_project", None)

    try:
        all_compare_tasks = []
        for hash_1, hash_2 in pairs:
            tasks_1 = get_simulation_tasks(simulation_project=project_for(hash_1), **kwargs_1, **kwargs)
            tasks_2 = get_simulation_tasks(simulation_project=project_for(hash_2), **kwargs_2, **kwargs)
            per_pair = get_compare_simulations_tasks(tasks_1, tasks_2, **kwargs)
            tag = f"[{hash_1[:8]}..{hash_2[:8]}]"
            for t in per_pair.tasks:
                t.name = f"{t.name} {tag}"
            all_compare_tasks.extend(per_pair.tasks)

        aggregate = MultipleSimulationTasks(
            tasks=all_compare_tasks, build=False,
            name=f"simulation comparison across {len(commits)} commits ({comparison_mode})",
            multiple_task_results_class=MultipleCompareSimulationsTaskResults, **kwargs)
        results = aggregate.run(**kwargs)
        _finalize_chart_comparisons(all_compare_tasks, results)
        _finalize_module_image_comparisons(all_compare_tasks, results)
        return results
    finally:
        if delete_worktree:
            for project in project_cache.values():
                remove_worktree_simulation_project(project)
compare_simulations_across_commits.__signature__ = combine_signatures(
    compare_simulations_across_commits, get_simulation_tasks, CompareSimulationsTask.__init__)

def compare_statistics_across_commits(**kwargs):
    """Compare only statistical results across a sequence of git commits.

    Thin wrapper around :py:func:`compare_simulations_across_commits` with
    stdout and fingerprint comparison disabled.
    """
    return compare_simulations_across_commits(compare_stdout=False, compare_fingerprint=False, **kwargs)
compare_statistics_across_commits.__signature__ = combine_signatures(
    compare_statistics_across_commits, compare_simulations_across_commits)

def compare_stdout_across_commits(**kwargs):
    """Compare only stdout trajectories across a sequence of git commits.

    Thin wrapper around :py:func:`compare_simulations_across_commits` with
    fingerprint and statistics comparison disabled.
    """
    return compare_simulations_across_commits(compare_fingerprint=False, compare_statistics=False, **kwargs)
compare_stdout_across_commits.__signature__ = combine_signatures(
    compare_stdout_across_commits, compare_simulations_across_commits)

def compare_fingerprints_across_commits(**kwargs):
    """Compare only fingerprint trajectories across a sequence of git commits.

    Thin wrapper around :py:func:`compare_simulations_across_commits` with
    stdout and statistics comparison disabled.
    """
    return compare_simulations_across_commits(compare_stdout=False, compare_statistics=False, **kwargs)
compare_fingerprints_across_commits.__signature__ = combine_signatures(
    compare_fingerprints_across_commits, compare_simulations_across_commits)

def _render_charts_for_working_directory(simulation_project, working_directory, staging_dir, suffix,
                                         chart_filter=None, exclude_chart_filter=None, dpi=150):
    """Render every matching chart in every ``.anf`` file under *working_directory*
    of *simulation_project* into ``<staging_dir>/<working_directory>/<image_export_filename><suffix>.png``.

    Returns the list of absolute paths that were rendered.
    """
    import omnetpp.scave.analysis
    workspace = omnetpp.scave.analysis.Workspace(get_workspace_path("."), [])
    wd_abs = simulation_project.get_full_path(working_directory)
    if not os.path.isdir(wd_abs):
        return []
    target_dir = os.path.join(staging_dir, working_directory)
    os.makedirs(target_dir, exist_ok=True)
    rendered = []
    for entry in sorted(os.listdir(wd_abs)):
        if not entry.endswith(".anf"):
            continue
        anf_abs = os.path.join(wd_abs, entry)
        try:
            analysis = omnetpp.scave.analysis.load_anf_file(anf_abs)
        except Exception as e:
            _logger.warning(f"Failed to load {anf_abs}: {e}")
            continue
        for chart in analysis.collect_charts():
            if not matches_filter(chart.name, chart_filter, exclude_chart_filter, False):
                continue
            image_export_filename = chart.properties.get("image_export_filename")
            if not image_export_filename:
                continue
            file_name = analysis.export_image(
                chart, wd_abs, workspace,
                format="png", dpi=dpi,
                target_folder=target_dir,
                filename=image_export_filename + suffix)
            rendered.append(os.path.join(wd_abs, file_name))
    return rendered

def _compute_compare_diffs(scope_dir):
    """Compute ``<stem>-diff.png`` for every ``<stem>-old.png`` / ``<stem>-new.png``
    pair beneath *scope_dir*."""
    from opp_repl.test.chart import compute_chart_image_diff
    if not os.path.isdir(scope_dir):
        return
    for dirpath, _dirs, files in os.walk(scope_dir):
        for fname in files:
            if not fname.endswith("-old.png"):
                continue
            stem = fname[:-len("-old.png")]
            old_file = os.path.join(dirpath, fname)
            new_file = os.path.join(dirpath, stem + "-new.png")
            diff_file = os.path.join(dirpath, stem + "-diff.png")
            if os.path.exists(diff_file):
                os.remove(diff_file)
            if not os.path.exists(new_file):
                continue
            metric = compute_chart_image_diff(old_file, new_file, diff_file_name=diff_file)
            if metric is None:
                _logger.warning(f"Cannot diff {old_file} and {new_file}: image shapes differ")

def _finalize_chart_comparisons(compare_tasks, multiple_compare_results):
    """Render charts and compute diffs in a single batch after every simulation
    has finished, then refresh chart verdicts on each result and recompute the
    aggregate verdict.

    A chart may aggregate results across multiple runs in the same working
    directory, so rendering must wait until every contributing run has
    populated the result folder. Per ``(staging_dir, working_directory, side)``
    we render exactly once even when many compare tasks share the same combo.
    """
    render_targets = {}  # (staging_dir, working_directory, suffix) -> (project, chart_filter, exclude_chart_filter)
    staging_dirs = set()
    for task in compare_tasks:
        if not (task.compare_charts and task.staging_dir):
            continue
        sub_tasks = task.multiple_simulation_tasks.tasks
        wd = sub_tasks[0].simulation_config.working_directory
        staging_dirs.add(task.staging_dir)
        render_targets.setdefault(
            (task.staging_dir, wd, "-old"),
            (sub_tasks[0].simulation_config.simulation_project, task.chart_filter, task.exclude_chart_filter))
        render_targets.setdefault(
            (task.staging_dir, wd, "-new"),
            (sub_tasks[1].simulation_config.simulation_project, task.chart_filter, task.exclude_chart_filter))
    if not render_targets:
        return
    for (staging_dir, wd, suffix), (project, cf, ecf) in render_targets.items():
        _render_charts_for_working_directory(
            project, wd, staging_dir, suffix=suffix,
            chart_filter=cf, exclude_chart_filter=ecf)
    for staging_dir in staging_dirs:
        _compute_compare_diffs(staging_dir)
    for result in multiple_compare_results.results:
        if getattr(result.task, "compare_charts", False):
            result._compute_chart_verdict()
            result._recompute_overall_result()
    _recompute_multiple_task_result(multiple_compare_results)

def _recompute_multiple_task_result(multi_result):
    """Recompute aggregate ``result``/``color`` after children's verdicts changed."""
    multi_result.num_different_results = 0
    multi_result.num_expected = {pr: multi_result.count_results(pr, True) for pr in multi_result.possible_results}
    multi_result.num_unexpected = {pr: multi_result.count_results(pr, False) for pr in multi_result.possible_results}
    multi_result.result = multi_result.expected_result if not multi_result.results else multi_result.possible_results[0]
    for pr in multi_result.possible_results:
        if multi_result.num_expected[pr] != 0:
            multi_result.result = pr
            break
    for pr in multi_result.possible_results:
        if multi_result.num_unexpected[pr] != 0:
            multi_result.result = pr
    multi_result.color = multi_result.possible_result_colors[multi_result.possible_results.index(multi_result.result)]
    multi_result.expected = multi_result.expected_result == multi_result.result

def _finalize_module_image_comparisons(compare_tasks, multiple_compare_results):
    """Capture each side's module images and diff them, then refresh the
    module-image verdict on each compare task.

    Module-image capture is more expensive than chart rendering: each side's
    simulation has to be launched a second time in Qtenv-with-MCP.  We bundle
    every per-side capture from every compare task into a single
    :class:`MultipleModuleImageCaptureTasks` so the port preassignment and
    process pool can be shared.
    """
    eligible = [t for t in compare_tasks if t.compare_module_images and t.staging_dir]
    if not eligible:
        return

    from opp_repl.test.module_image import (
        ModuleImageCaptureTask, MultipleModuleImageCaptureTasks)

    capture_tasks = []
    staging_dirs = set()
    for task in eligible:
        sub_tasks = task.multiple_simulation_tasks.tasks
        wd = sub_tasks[0].simulation_config.working_directory
        out_dir = os.path.join(task.staging_dir, wd, "module_images")
        staging_dirs.add(os.path.join(task.staging_dir, wd, "module_images"))
        common_kwargs = dict(
            output_dir=out_dir,
            module_path_filter=task.module_path_filter,
            exclude_module_path_filter=task.exclude_module_path_filter,
            module_type_filter=task.module_type_filter,
            exclude_module_type_filter=task.exclude_module_type_filter,
            group_by=task.group_by, area=task.area, margin=task.margin,
            startup_timeout=task.startup_timeout,
        )
        for side_index, sub_task, suffix in [(0, sub_tasks[0], "-old"),
                                              (1, sub_tasks[1], "-new")]:
            capture_tasks.append(ModuleImageCaptureTask(
                simulation_config=sub_task.simulation_config,
                run_number=sub_task.run_number,
                mode=sub_task.mode,
                filename_suffix=suffix,
                **common_kwargs))
    # Build skipped: both projects were built when the compare ran.
    multiple = MultipleModuleImageCaptureTasks(
        tasks=capture_tasks,
        simulation_project=eligible[0].multiple_simulation_tasks.tasks[0].simulation_config.simulation_project,
        build=False, name="module image capture (compare)")
    multiple.run()
    # Diff every -old / -new pair.
    for scope in staging_dirs:
        _compute_compare_diffs(scope)
    # Refresh per-task and aggregate verdicts.
    for result in multiple_compare_results.results:
        if getattr(result.task, "compare_module_images", False):
            result._compute_module_image_verdict()
            result._recompute_overall_result()
    _recompute_multiple_task_result(multiple_compare_results)


def _launch_diffcharts_gui(staging_dir):
    """Open *staging_dir* in the :command:`opp_diff_charts` GUI without blocking
    the caller.

    Prefers the ``opp_diff_charts`` console script; falls back to running the
    module via ``python -m opp_repl.diffcharts`` if the script is not on PATH.
    """
    try:
        return subprocess.Popen(["opp_diff_charts", staging_dir])
    except FileNotFoundError:
        return subprocess.Popen([sys.executable, "-m", "opp_repl.diffcharts", staging_dir])

def compare_charts(open_gui=True, **kwargs):
    """Compare chart images between two simulation projects.

    Thin wrapper around :py:func:`compare_simulations` with only the chart
    axis enabled.  Runs each matching simulation pair, renders both sides'
    charts into a shared staging folder, computes per-chart diffs, and (if
    *open_gui* is true) opens the result in the :command:`opp_diff_charts` GUI.

    Parameters:
        open_gui (bool):
            If ``True`` (default), launch the GUI on the staging folder once
            all tasks complete.  Set to ``False`` to inspect results
            programmatically (the path is on ``results.staging_dir``).
        kwargs:
            Forwarded to :py:func:`compare_simulations`.  Notable keys:
            ``simulation_project_1`` / ``_2``, ``working_directory_filter``,
            ``config_filter``, ``run_number``, ``chart_filter`` /
            ``exclude_chart_filter``, ``staging_dir``.

    Returns:
        :py:class:`MultipleCompareSimulationsTaskResults`
    """
    results = compare_simulations(
        compare_stdout=False, compare_fingerprint=False, compare_statistics=False,
        compare_charts=True, **kwargs)
    if open_gui and results.staging_dir:
        results.open_charts_in_gui()
    return results
compare_charts.__signature__ = combine_signatures(compare_charts, compare_simulations)

def compare_charts_between_commits(open_gui=True, **kwargs):
    """Compare chart images between two git versions of the same project.

    Thin wrapper around :py:func:`compare_simulations_between_commits` with
    only the chart axis enabled.

    Parameters:
        open_gui (bool):
            If ``True`` (default), launch the :command:`opp_diff_charts` GUI
            on the staging folder once all tasks complete.
        kwargs:
            Forwarded to :py:func:`compare_simulations_between_commits`.
            Notable keys: ``simulation_project``, ``git_hash_1``,
            ``git_hash_2``, ``working_directory_filter``, ``chart_filter``,
            ``staging_dir``, ``delete_worktree``.

    Returns:
        :py:class:`MultipleCompareSimulationsTaskResults`

    Example::

        compare_charts_between_commits(
            simulation_project=inet_gm,
            git_hash_1="master",
            git_hash_2="topic/desync",
            working_directory_filter="examples/ethernet/gm")
    """
    results = compare_simulations_between_commits(
        compare_stdout=False, compare_fingerprint=False, compare_statistics=False,
        compare_charts=True, **kwargs)
    if open_gui and results.staging_dir:
        results.open_charts_in_gui()
    return results
compare_charts_between_commits.__signature__ = combine_signatures(compare_charts_between_commits, compare_simulations_between_commits)

def compare_module_images(open_gui=True, **kwargs):
    """Compare module images between two simulation projects.

    Thin wrapper around :py:func:`compare_simulations` with only the
    module-image axis enabled.  Runs each matching simulation pair, then
    launches each side's simulation a second time in Qtenv with its MCP
    server enabled to capture per-compound-module PNGs into a shared staging
    folder; the captures get ``-old`` / ``-new`` suffixes and per-image
    diffs are computed.  If *open_gui* is true, the staging folder is
    opened in the :command:`opp_diff_charts` GUI.

    Parameters:
        open_gui (bool):
            If ``True`` (default), launch the GUI on the staging folder once
            all tasks complete.  Set to ``False`` to inspect results
            programmatically (the path is on ``results.staging_dir``).
        kwargs:
            Forwarded to :py:func:`compare_simulations`.  Notable keys:
            ``simulation_project_1`` / ``_2``, ``working_directory_filter``,
            ``config_filter``, ``run_number``, ``module_path_filter`` /
            ``exclude_module_path_filter``, ``module_type_filter`` /
            ``exclude_module_type_filter``, ``group_by``, ``area``,
            ``margin``, ``startup_timeout``, ``staging_dir``.

    Returns:
        :py:class:`MultipleCompareSimulationsTaskResults`
    """
    results = compare_simulations(
        compare_stdout=False, compare_fingerprint=False, compare_statistics=False,
        compare_module_images=True, **kwargs)
    if open_gui and results.staging_dir:
        # Reuse the chart-diff GUI on the module-image subdir of any task's
        # working directory.  Pick the first eligible task to choose the dir.
        for r in results.results:
            staging = getattr(r.task, "staging_dir", None)
            if not staging:
                continue
            wd = r.task.multiple_simulation_tasks.tasks[0].simulation_config.working_directory
            scope = os.path.join(staging, wd, "module_images")
            if os.path.isdir(scope):
                _launch_diffcharts_gui(scope)
                break
    return results
compare_module_images.__signature__ = combine_signatures(compare_module_images, compare_simulations)


def compare_module_images_between_commits(open_gui=True, **kwargs):
    """Compare module images between two git versions of the same project.

    Thin wrapper around :py:func:`compare_simulations_between_commits` with
    only the module-image axis enabled.

    Parameters:
        open_gui (bool):
            If ``True`` (default), launch the :command:`opp_diff_charts` GUI
            on the staging folder once all tasks complete.
        kwargs:
            Forwarded to :py:func:`compare_simulations_between_commits`.
            Notable keys: ``simulation_project``, ``git_hash_1``,
            ``git_hash_2``, ``working_directory_filter``,
            ``module_type_filter``, ``group_by``, ``staging_dir``,
            ``delete_worktree``.

    Returns:
        :py:class:`MultipleCompareSimulationsTaskResults`
    """
    results = compare_simulations_between_commits(
        compare_stdout=False, compare_fingerprint=False, compare_statistics=False,
        compare_module_images=True, **kwargs)
    if open_gui and results.staging_dir:
        for r in results.results:
            staging = getattr(r.task, "staging_dir", None)
            if not staging:
                continue
            wd = r.task.multiple_simulation_tasks.tasks[0].simulation_config.working_directory
            scope = os.path.join(staging, wd, "module_images")
            if os.path.isdir(scope):
                _launch_diffcharts_gui(scope)
                break
    return results
compare_module_images_between_commits.__signature__ = combine_signatures(
    compare_module_images_between_commits, compare_simulations_between_commits)


def compare_speed(**kwargs):
    """Compare simulation speed (CPU instruction counts) between two projects.

    Not yet implemented.
    """
    raise NotImplementedError("compare_speed is not yet implemented")

def compare_speed_between_commits(simulation_project=None, git_hash_1=None, git_hash_2=None, **kwargs):
    """Compare simulation speed between two git versions.

    Not yet implemented.
    """
    raise NotImplementedError("compare_speed_between_commits is not yet implemented")
