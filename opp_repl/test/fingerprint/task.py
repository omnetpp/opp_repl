"""
This module provides functionality for fingerprint testing of multiple simulations.

The main function is :py:func:`run_fingerprint_tests`. It allows running multiple fingerprint tests matching the provided
filter criteria. Fingerprint tests check for regressions in the simulation execution trajectory.
"""

import hashlib
import logging
import re

from opp_repl.simulation.task import *

from opp_repl.common.ide import *
from opp_repl.simulation.project import *
from opp_repl.test.fingerprint.store import *
from opp_repl.test.simulation import *

_logger = logging.getLogger(__name__)
all_fingerprint_ingredients = ["tplx", "~tNl", "~tND", "tyf"]
all_fingerprint_ingredients_append_args = {
    "~tNl": {},
    "~tND": {"--**.checksumMode=\"computed\"",
             "--**.crcMode=\"computed\"",
             "--**.fcsMode=\"computed\""},
    # the values of INET's former fingerprinttest, which recorded INET's tyf fingerprints
    "tyf" : {"--cmdenv-fake-gui=true",
             "--cmdenv-fake-gui-before-event-probability=0.001",
             "--cmdenv-fake-gui-after-event-probability=0.001",
             "--cmdenv-fake-gui-on-hold-probability=0.001",
             "--cmdenv-fake-gui-on-hold-numsteps=3",
             "--cmdenv-fake-gui-on-simtime-probability=0.001",
             "--cmdenv-fake-gui-on-simtime-numsteps=3",
             "--**.fadeOutMode=\"animationTime\"",
             "--**.signalAnimationSpeedChangeTimeMode=\"animationTime\""}}

def get_ingredients_append_args(ingredients):
    global all_fingerprint_ingredients_append_args
    # Single =-joined token (not two list items): these ingredient args are
    # deduplicated through a set() by the caller, which would otherwise split the
    # option from its value and reorder them, leaving "inet::FingerprintCalculator"
    # as a bare positional that opp_run treats as an ini file ("Cannot open ini
    # file"). Matches OMNeT++'s own opp_fingerprinttest and the =-joined form of
    # every other entry in all_fingerprint_ingredients_append_args.
    append_args = ["--fingerprintcalculator-class=inet::FingerprintCalculator"] if "~" in ingredients else []
    # an ingredient without extra arguments (for example ~tNlb) still needs the calculator
    return append_args + list(all_fingerprint_ingredients_append_args.get(ingredients, []))

class FingerprintTestTaskResult(SimulationTestTaskResult):
    def __init__(self, expected_fingerprint=None, calculated_fingerprint=None, **kwargs):
        super().__init__(**kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.expected_fingerprint = expected_fingerprint
        self.calculated_fingerprint = calculated_fingerprint
        self.fingerprint_mismatch = expected_fingerprint != calculated_fingerprint

    def __repr__(self):
        return "Fingerprint test result: " + self.get_description()

    def get_description(self, **kwargs):
        return super().get_description(**kwargs) + (" calculated " + str(self.calculated_fingerprint) + " (correct " + str(self.expected_fingerprint) + ")" if self.fingerprint_mismatch else "")

    def print_result(self, test_result_filter=None, exclude_test_result_filter="SKIP", complete_error_message=True, output_stream=sys.stdout, **kwargs):
        if matches_filter(self.result, test_result_filter, exclude_test_result_filter, True):
            print(self.get_description(complete_error_message=complete_error_message), file=output_stream)

    def run_baseline_fingerprint_test(self, baseline_simulation_project=None, **kwargs):
        simulation_task = self.simulation_result.simulation_task
        simulation_config = self.simulation_result.simulation_task.simulation_config
        multiple_test_tasks = get_fingerprint_test_tasks(simulation_project=baseline_simulation_project, ingredients_list=[self.task.ingredients], full_match=True,
                                                         working_directory_filter=simulation_config.working_directory, ini_file_filter=simulation_config.ini_file, config_filter=simulation_config.config, run_number=simulation_task.run_number,
                                                         **kwargs)
        assert(len(multiple_test_tasks.tasks) == 1)
        multiple_test_results = multiple_test_tasks.run(**kwargs)
        return multiple_test_results.results[0]

class MultipleFingerprintTestTaskResults(MultipleTestTaskResults):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs

class FingerprintTestTask(SimulationTestTask):
    def __init__(self, sim_time_limit=None, ingredients="tplx", fingerprint=None, test_result=None, name="fingerprint test", action="Checking fingerprint", task_result_class=FingerprintTestTaskResult, **kwargs):
        super().__init__(name=name, action=action, task_result_class=task_result_class, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.sim_time_limit = sim_time_limit
        self.ingredients = ingredients
        self.fingerprint = fingerprint
        self.test_result = test_result

    def __repr__(self):
        return repr(self)

    def get_hash(self, **kwargs):
        hasher = hashlib.sha256()
        digest = super().get_hash(**kwargs)
        if digest:
            hasher.update(digest)
        else:
            return None
        hasher.update(self.ingredients.encode("utf-8"))
        return hasher.digest()

    def run(self, test_result_filter=None, exclude_test_result_filter="SKIP", output_stream=sys.stdout, **kwargs):
        if self.fingerprint and self.sim_time_limit is None:
            # a stored fingerprint without its limit cannot be reproduced: report the
            # store defect instead of running an unbounded simulation or dropping it
            if matches_filter("ERROR", test_result_filter, exclude_test_result_filter, True):
                print("Running " + self.simulation_task.get_parameters_string(**kwargs), end=" ", file=output_stream)
            return FingerprintTestTaskResult(task=self, result="ERROR", expected_result="PASS", reason="No sim-time-limit in the fingerprint store")
        elif self.fingerprint and matches_filter(self.test_result, test_result_filter, exclude_test_result_filter, True):
            simulation_project = self.simulation_task.simulation_config.simulation_project
            return super().run(append_args=self.get_append_args(simulation_project, str(self.fingerprint)) + get_ingredients_append_args(self.ingredients), output_stream=output_stream, **kwargs)
        else:
            if matches_filter("SKIP", test_result_filter, exclude_test_result_filter, True):
                print("Running " + self.simulation_task.get_parameters_string(**kwargs), end=" ", file=output_stream)
            return FingerprintTestTaskResult(task=self, result="SKIP", expected_result=self.test_result, reason="Correct fingerprint not found")

    def check_simulation_task_result(self, simulation_task_result, **kwargs):
        expected_fingerprint = self.fingerprint
        expected_result = self.test_result
        if simulation_task_result.result == "CANCEL":
            result = "CANCEL"
            reason = "Cancel by user"
            calculated_fingerprint = None
        else:
            calculated_fingerprint = get_calculated_fingerprint(simulation_task_result, self.fingerprint.ingredients)
            if calculated_fingerprint is None:
                result = "ERROR"
                reason = "Calculated fingerprint not found"
            elif expected_fingerprint != calculated_fingerprint:
                result = "FAIL"
                reason = "Fingerprint mismatch"
            else:
                result = "PASS"
                reason = None
        return FingerprintTestTaskResult(task=self, simulation_task_result=simulation_task_result, expected_fingerprint=expected_fingerprint, calculated_fingerprint=calculated_fingerprint, result=result, expected_result=expected_result, reason=reason)

    def get_append_args(self, simulation_project, fingerprint_arg):
        return ["--fingerprint", fingerprint_arg, "--vector-recording", "false", "--scalar-recording", "false"]

class FingerprintTestGroupTask(MultipleTestTasks):
    def __init__(self, sim_time_limit=None, **kwargs):
        super().__init__(**kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        for fingerprint_test_task in self.tasks:
            assert fingerprint_test_task.sim_time_limit == sim_time_limit
        self.sim_time_limit = sim_time_limit

    def __repr__(self):
        return repr(self)

    def count_progress_steps(self):
        # When a group has a single task, or no sim_time_limit, run() runs each
        # task by itself and does not fire its own ▶/◉ events, so don't count an
        # extra step.
        if len(self.tasks) == 1 or self.sim_time_limit is None:
            return sum(t.count_progress_steps() for t in self.tasks)
        # A multi-ingredient group runs ONE simulation for all checked
        # (fingerprint-present) ingredients — not one per ingredient — plus one
        # run per skipped (fingerprint-None) task. Summing every ingredient task
        # (super()) inflated the progress denominator ~Nx.
        skipped = [t for t in self.tasks if t.fingerprint is None]
        checked = [t for t in self.tasks if t.fingerprint]
        return sum(t.count_progress_steps() for t in skipped) + (checked[0].count_progress_steps() if checked else 0)

    def run(self, output_stream=sys.stdout, sim_time_limit=None, **kwargs):
        if len(self.tasks) == 1:
            return self.tasks[0].run(output_stream=output_stream, **kwargs)
        elif self.sim_time_limit is None:
            # each task reports the absent limit itself, see FingerprintTestTask.run
            return MultipleTestTaskResults(self, [task.run(output_stream=output_stream, **kwargs) for task in self.tasks])
        else:
            fingerprint_test_results = []
            skipped_fingerprint_test_tasks = list(filter(lambda fingerprint_test_task: fingerprint_test_task.fingerprint is None, self.tasks))
            for skipped_fingerprint_test_task in skipped_fingerprint_test_tasks:
                fingerprint_test_results.append(skipped_fingerprint_test_task.run(**kwargs))
            checked_fingerprint_test_tasks = list(filter(lambda fingerprint_test_task: fingerprint_test_task.fingerprint, self.tasks))
            if checked_fingerprint_test_tasks:
                simulation_task = checked_fingerprint_test_tasks[0].simulation_task
                simulation_project = simulation_task.simulation_config.simulation_project
                fingerprint_arg = ",".join(map(lambda e: str(e.fingerprint), checked_fingerprint_test_tasks))
                append_args = checked_fingerprint_test_tasks[0].get_append_args(simulation_project, fingerprint_arg)
                ingredients_append_args = set()
                for checked_fingerprint_test_task in checked_fingerprint_test_tasks:
                    ingredients_append_args = ingredients_append_args.union(get_ingredients_append_args(checked_fingerprint_test_task.ingredients))
                simulation_result = simulation_task.run(print_end=" ", sim_time_limit=sim_time_limit or self.sim_time_limit, output_stream=output_stream, append_args=append_args + list(ingredients_append_args), **kwargs)
                fingerprint_test_group_results = check_fingerprint_test_group(simulation_result, self, **kwargs)
                fingerprint_test_results += fingerprint_test_group_results.results
            return MultipleTestTaskResults(self, fingerprint_test_results)

class MultipleFingerprintTestTasks(MultipleSimulationTestTasks):
    def __init__(self, multiple_simulation_tasks=None, name="fingerprint test", **kwargs):
        super().__init__(name=name, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.multiple_simulation_tasks = multiple_simulation_tasks

class FingerprintTrajectoryTestTask(TestTask):
    def __init__(self, simulation_task, sim_time_limit, ingredients, **kwargs):
        super().__init__(simulation_task, **kwargs)
        self.sim_time_limit = sim_time_limit
        self.ingredients = ingredients
        # TODO

class FingerprintTrajectoryTestTaskResult(TestTaskResult):
    def __init__(self):
        # TODO
        pass

def get_calculated_fingerprint(simulation_result, ingredients):
    stdout = simulation_result.subprocess_result.stdout
    stderr = simulation_result.subprocess_result.stderr
    # the whole ingredient string: ~tNl must not match the value of ~tNlb in the same run
    ingredients_pattern = re.escape(ingredients) + r"(?![\w~])"
    match = re.search(r"Fingerprint successfully verified:.*? ([0-9a-f]{4}-[0-9a-f]{4})/" + ingredients_pattern, stdout)
    if match:
        value = match.groups()[0]
    else:
        match = re.search(r"Fingerprint mismatch! calculated:.*? ([0-9a-f]{4}-[0-9a-f]{4})/" + ingredients_pattern + ".*expected", stdout)
        if match:
            value = match.groups()[0]
        else:
            match = re.search(r"Fingerprint mismatch! calculated:.*? ([0-9a-f]{4}-[0-9a-f]{4})/" + ingredients_pattern + ".*expected", stderr)
            if match:
                value = match.groups()[0]
            else:
                return None
    return Fingerprint(value, ingredients)

def check_fingerprint_test_group(simulation_result, fingerprint_test_group, **kwargs):
    fingerprint_test_results = []
    for fingerprint_test_task in fingerprint_test_group.tasks:
        if fingerprint_test_task.fingerprint:
            fingerprint_test_result = fingerprint_test_task.check_simulation_task_result(simulation_result, **kwargs)
            fingerprint_test_results.append(fingerprint_test_result)
    return MultipleTestTaskResults(fingerprint_test_group, fingerprint_test_results)

def select_fingerprint_by_sim_time_limit(fingerprint_entries, largest):
    # an entry without a limit is selected only if no entry has one; it reports ERROR
    fingerprint_entries = [e for e in fingerprint_entries if e["sim_time_limit"] is not None] or fingerprint_entries
    sim_time_limits = list(map(lambda fingerprint_entry: fingerprint_entry["sim_time_limit"], fingerprint_entries))
    sim_time_limits.sort(reverse=largest, key=lambda sim_time_limit: convert_to_seconds(sim_time_limit) if sim_time_limit is not None else 0)
    smallest_sim_time_limit = sim_time_limits[0]
    sorted_fingerprint_entries = list(filter(lambda fingerprint_entry: fingerprint_entry["sim_time_limit"] == smallest_sim_time_limit, fingerprint_entries))
    sorted_fingerprint_entries.sort(reverse=True, key=lambda fingerprint_entry: fingerprint_entry["timestamp"])
    return sorted_fingerprint_entries[0]

def select_fingerprint_with_smallest_sim_time_limit(fingerprint_entries):
    return select_fingerprint_by_sim_time_limit(fingerprint_entries, False)

def select_fingerprint_with_largest_sim_time_limit(fingerprint_entries):
    return select_fingerprint_by_sim_time_limit(fingerprint_entries, True)

select_fingerprint_aliases = {
    "shortest": select_fingerprint_with_smallest_sim_time_limit,
    "longest": select_fingerprint_with_largest_sim_time_limit,
}

def get_fingerprint_test_task(simulation_task, ingredients="tplx", sim_time_limit=None, select_fingerprint=None, baseline_simulation_project=None, **kwargs):
    if isinstance(select_fingerprint, str):
        if select_fingerprint not in select_fingerprint_aliases:
            raise ValueError(f"unknown select_fingerprint alias {select_fingerprint!r}; expected one of {sorted(select_fingerprint_aliases)}")
        select_fingerprint = select_fingerprint_aliases[select_fingerprint]
    simulation_config = simulation_task.simulation_config
    baseline_project = baseline_simulation_project or simulation_config.simulation_project
    correct_fingerprint_store = get_correct_fingerprint_store(baseline_project)
    # When the caller provides a selector, search across all stored sim_time_limits
    # and let the selector pick one. Otherwise filter by the explicit sim_time_limit
    # (defaulting to the one from the simulation task / INI).
    if select_fingerprint is None:
        if sim_time_limit is None:
            sim_time_limit = simulation_task.sim_time_limit
        filter_sim_time_limit = sim_time_limit
        effective_select = select_fingerprint_with_smallest_sim_time_limit
    else:
        filter_sim_time_limit = None
        effective_select = select_fingerprint
    entry_filter = dict(ingredients=ingredients, working_directory=simulation_config.working_directory, ini_file=simulation_config.ini_file, config=simulation_config.config, run_number=simulation_task.run_number)
    stored_fingerprint_entries = correct_fingerprint_store.filter_entries(sim_time_limit=filter_sim_time_limit, **entry_filter)
    if not stored_fingerprint_entries:
        # an entry without a limit matches no limit filter, but it must not vanish
        stored_fingerprint_entries = [e for e in correct_fingerprint_store.filter_entries(sim_time_limit=None, **entry_filter) if e["sim_time_limit"] is None]
    selected_fingerprint_entry = effective_select(stored_fingerprint_entries) if stored_fingerprint_entries else None
    if selected_fingerprint_entry:
        sim_time_limit = selected_fingerprint_entry["sim_time_limit"]
        fingerprint = selected_fingerprint_entry["fingerprint"]
        test_result = selected_fingerprint_entry["test_result"]
        if sim_time_limit is not None:
            simulation_task.sim_time_limit = sim_time_limit
        return FingerprintTestTask(simulation_task=simulation_task, sim_time_limit=sim_time_limit, ingredients=ingredients, fingerprint=Fingerprint(fingerprint, ingredients), test_result=test_result)
    else:
        if sim_time_limit is None:
            sim_time_limit = simulation_task.sim_time_limit
        simulation_task.sim_time_limit = sim_time_limit
        fingerprint_test_task = FingerprintTestTask(simulation_task=simulation_task, sim_time_limit=sim_time_limit, ingredients=ingredients, test_result=None)
    return fingerprint_test_task

def collect_fingerprint_test_groups(simulation_task, ingredients_list=None, sim_time_limit=None, stored_only=False, **kwargs):
    if ingredients_list is None:
        # No explicit list → consider every known ingredient.
        ingredients_list = all_fingerprint_ingredients
    fingerprint_test_tasks = []
    for ingredients in ingredients_list:
        fingerprint_test_task = get_fingerprint_test_task(simulation_task, ingredients=ingredients, sim_time_limit=sim_time_limit, **kwargs)
        # An unstored task without a limit cannot run bounded, so it is dropped. A
        # stored task without a limit stays, and reports ERROR when it runs.
        if fingerprint_test_task and (fingerprint_test_task.fingerprint or fingerprint_test_task.sim_time_limit):
            # get_fingerprint_test_task returns a fingerprint=None (SKIP) task when
            # this (config, run, ingredient) has no stored fingerprint. Under
            # stored_only, drop those so we run exactly the stored fingerprints
            # instead of emitting a SKIP row for every unstored ingredient.
            if stored_only and not fingerprint_test_task.fingerprint:
                continue
            fingerprint_test_tasks.append(fingerprint_test_task)
    def get_sim_time_limit(element):
        return element.sim_time_limit
    def get_fingerprint_test_group_task(fingerprint_test_tasks):
        return FingerprintTestGroupTask(sim_time_limit=fingerprint_test_tasks[0].sim_time_limit, tasks=list(fingerprint_test_tasks))
    sorted_fingerprint_test_tasks = sorted(fingerprint_test_tasks, key=lambda element: (element.sim_time_limit is not None, element.sim_time_limit or ""))
    grouped_fingerprint_test_tasks = [list(it) for k, it in itertools.groupby(sorted_fingerprint_test_tasks, get_sim_time_limit)]
    return list(map(get_fingerprint_test_group_task, grouped_fingerprint_test_tasks))

def copy_simulation_task(simulation_task, **kwargs):
    return SimulationTask(**{**dict(simulation_config=simulation_task.simulation_config, run_number=simulation_task.run_number,
                                    mode=simulation_task.mode, build=simulation_task.build, debug=simulation_task.debug,
                                    sim_time_limit=simulation_task.sim_time_limit, cpu_time_limit=simulation_task.cpu_time_limit,
                                    user_interface=simulation_task.user_interface), **kwargs})

def get_stored_simulation_tasks(multiple_simulation_tasks, correct_fingerprint_store):
    """
    Returns the simulation tasks of the runs that have a stored fingerprint: the tasks of multiple_simulation_tasks
    whose ``(working_directory, ini_file, config, run_number)`` is in the store, and one task for each stored
    iteration-variable run filter of a config in multiple_simulation_tasks.
    """
    stored_keys = {(entry["working_directory"], entry["ini_file"], entry["config"], entry["run_number"])
                   for entry in correct_fingerprint_store.get_entries()}
    simulation_tasks = [simulation_task for simulation_task in multiple_simulation_tasks.tasks
                        if (simulation_task.simulation_config.working_directory, simulation_task.simulation_config.ini_file,
                            simulation_task.simulation_config.config, simulation_task.run_number) in stored_keys]
    # Iteration-variable run filters (string run_number, e.g. "$datarate==... &&
    # $repetition==0" parameter studies) are not enumerated by get_simulation_tasks
    # (which only produces integer runs), so build a task for each straight from
    # the store: clone an enumerated task of the same config and pass the filter
    # through as the run spec (SimulationTask emits it as opp_run -r '<filter>').
    template_by_config = {}
    for simulation_task in multiple_simulation_tasks.tasks:
        simulation_config = simulation_task.simulation_config
        template_by_config.setdefault((simulation_config.working_directory, simulation_config.ini_file, simulation_config.config), simulation_task)
    for working_directory, ini_file, config, run in stored_keys:
        if not isinstance(run, str):
            continue
        template = template_by_config.get((working_directory, ini_file, config))
        if template is not None:
            simulation_tasks.append(copy_simulation_task(template, run_number=run, sim_time_limit=None))
    return simulation_tasks

def get_fingerprint_test_tasks(stored_only=False, **kwargs):
    """
    Returns multiple fingerprint test tasks matching the provided filter criteria. The returned tasks can be run by
    calling the :py:meth:`run <opp_repl.common.task.MultipleTasks.run>` method.

    Parameters:
        stored_only (bool):
            When True, restrict discovery to the ``(working_directory, ini_file,
            config, run_number)`` pairs that actually have a stored fingerprint.
            Without it, every ini run (``0..num_runs-1``) of every fingerprint
            config is enumerated and then SKIPped when the store has no entry —
            for INET that is ~93000 tasks of which only ~1500 are real. Projects
            declare this in their ``.opp`` ``test_parameters["fingerprint"]``.

        kwargs (dict):
            The filter criteria parameters are inherited from the :py:meth:`get_simulation_tasks <opp_repl.simulation.task.get_simulation_tasks>` method.

    Returns (:py:class:`MultipleFingerprintTestTasks`):
        an object that contains a list of :py:class:`FingerprintTestTask` objects matching the provided filter criteria.
        The result can be run (and re-run) without providing additional parameters.
    """
    kwargs.setdefault("mode", "debug")
    def get_tasks(**kwargs):
        multiple_simulation_tasks = get_simulation_tasks(**kwargs)
        simulation_tasks = multiple_simulation_tasks.tasks
        if stored_only:
            baseline_project = kwargs.get("baseline_simulation_project") or multiple_simulation_tasks.simulation_project
            simulation_tasks = get_stored_simulation_tasks(multiple_simulation_tasks, get_correct_fingerprint_store(baseline_project))
        fingerprint_test_groups = []
        for simulation_task in simulation_tasks:
            fingerprint_test_groups += collect_fingerprint_test_groups(simulation_task, stored_only=stored_only, **dict(kwargs, pass_keyboard_interrupt=True))
        return MultipleFingerprintTestTasks(multiple_simulation_tasks=multiple_simulation_tasks, tasks=fingerprint_test_groups, **dict(kwargs, simulation_project=multiple_simulation_tasks.simulation_project))
    return get_tasks(**kwargs)
get_fingerprint_test_tasks.__signature__ = combine_signatures(get_fingerprint_test_tasks, collect_fingerprint_test_groups, get_fingerprint_test_task, get_simulation_tasks)

def run_fingerprint_tests(**kwargs):
    """
    Runs one or more fingerprint tests that match the provided filter criteria.

    Parameters:
        kwargs (dict):
            The filter criteria parameters are inherited from the :py:func:`get_fingerprint_test_tasks` function.

    Returns (:py:class:`MultipleFingerprintTestTaskResults`):
        an object that contains a list of :py:class:`FingerprintTestTaskResult` objects. Each object describes the result of running one test task.
    """
    kwargs = apply_project_test_defaults("fingerprint", kwargs)
    multiple_fingerprint_test_tasks = get_fingerprint_test_tasks(**kwargs)
    return multiple_fingerprint_test_tasks.run(**kwargs)
run_fingerprint_tests.__signature__ = combine_signatures(run_fingerprint_tests, get_fingerprint_test_tasks)

def print_correct_fingerprints(**kwargs):
    multiple_test_tasks = get_fingerprint_test_tasks(**kwargs)
    for test_task in multiple_test_tasks.tasks:
        print(test_task.simulation_task.get_parameters_string(**kwargs) + " " + COLOR_GREEN + str(test_task.fingerprint) + COLOR_RESET)
print_correct_fingerprints.__signature__ = combine_signatures(print_correct_fingerprints, get_fingerprint_test_tasks)

def print_missing_correct_fingerprints(simulation_project=None, ingredients="tplx", num_runs=1, build=None, mode="release", build_engine=None):
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    # is_interactive() runs the project executable to probe for interactive
    # prompts, so the project must already be built. Build once up front and
    # construct each SimulationTask with build=False so per-task probing
    # doesn't trigger redundant make invocations.
    if build is None:
        build = get_default_build_argument()
    if build:
        simulation_project.build(mode=mode, build_engine=build_engine)
    correct_fingerprint_store = get_correct_fingerprint_store(simulation_project)
    for simulation_config in simulation_project.get_all_simulation_configs(build=False, mode=mode):
        if not simulation_config.abstract and not simulation_config.emulation:
            for run_number in range(0, num_runs or simulation_config.num_runs):
                simulation_task = SimulationTask(simulation_config=simulation_config, run_number=run_number, mode=mode, build=False)
                if not simulation_task.is_interactive():
                    stored_fingerprint_entries = correct_fingerprint_store.filter_entries(ingredients=ingredients, working_directory=simulation_config.working_directory, ini_file=simulation_config.ini_file, config=simulation_config.config, run_number=run_number)
                    if len(stored_fingerprint_entries) == 0:
                        print(simulation_task.get_parameters_string())

def insert_missing_correct_fingerprints(source_ingredients, target_ingredients, simulation_project=None, **kwargs):
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    correct_fingerprint_store = get_correct_fingerprint_store(simulation_project)
    multiple_simulation_tasks = get_simulation_tasks(**kwargs)
    for simulation_task in multiple_simulation_tasks.tasks:
        simulation_config = simulation_task.simulation_config
        simulation_project = simulation_config.simulation_project
        working_directory = simulation_config.working_directory
        ini_file = simulation_config.ini_file
        config = simulation_config.config
        run_number = simulation_task.run_number
        for source_entry in correct_fingerprint_store.filter_entries(ingredients=source_ingredients, working_directory=working_directory, ini_file=ini_file, config=config, run_number=run_number):
            sim_time_limit = source_entry["sim_time_limit"]
            target_entries = correct_fingerprint_store.filter_entries(ingredients=target_ingredients, working_directory=working_directory, ini_file=ini_file, config=config, run_number=run_number, sim_time_limit=sim_time_limit)
            if len(target_entries) == 0:
                correct_fingerprint_store.insert_fingerprint("0000-0000/" + target_ingredients, ingredients=target_ingredients, working_directory=working_directory, ini_file=ini_file, config=config, run_number=run_number, sim_time_limit=sim_time_limit, test_result=source_entry["test_result"])

class FingerprintUpdateTask(SimulationUpdateTask):
    """
    Records the fingerprints of one run at one sim_time_limit with one simulation: the simulation_task carries the
    run and the limit, and ingredients_list names the ingredients to record.
    """
    def __init__(self, ingredients_list=["tplx"], expected_error=False, action="Updating fingerprint", **kwargs):
        super().__init__(action=action, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.ingredients_list = ingredients_list
        self.expected_error = expected_error

    def get_stored_fingerprint_entry(self, ingredients):
        simulation_config = self.simulation_task.simulation_config
        correct_fingerprint_store = get_correct_fingerprint_store(simulation_config.simulation_project)
        return correct_fingerprint_store.find_entry(ingredients=ingredients, sim_time_limit=self.simulation_task.sim_time_limit,
                                                    working_directory=simulation_config.working_directory, ini_file=simulation_config.ini_file, config=simulation_config.config, run_number=self.simulation_task.run_number)

    def run_protected(self, append_args=[], output_stream=sys.stdout, **kwargs):
        expected_result = "ERROR" if self.expected_error else "KEEP"
        if self.simulation_task.sim_time_limit is None:
            return FingerprintUpdateTaskResult(task=self, result="ERROR", expected_result=expected_result, reason="No sim-time-limit in the fingerprint store or in the ini file")
        fingerprint_arg = ",".join(map(lambda ingredients: "0000-0000/" + ingredients, self.ingredients_list))
        ingredients_append_args = set()
        for ingredients in self.ingredients_list:
            ingredients_append_args = ingredients_append_args.union(get_ingredients_append_args(ingredients))
        fingerprint_append_args = ["--fingerprint", fingerprint_arg, "--vector-recording", "false", "--scalar-recording", "false"] + sorted(ingredients_append_args)
        simulation_task_result = self.simulation_task.run_protected(output_stream=output_stream, append_args=fingerprint_append_args + append_args, **kwargs)
        ingredient_updates = []
        for ingredients in self.ingredients_list:
            stored_fingerprint_entry = self.get_stored_fingerprint_entry(ingredients)
            ingredient_updates.append((ingredients, stored_fingerprint_entry, get_calculated_fingerprint(simulation_task_result, ingredients)))
        return FingerprintUpdateTaskResult(task=self, simulation_task_result=simulation_task_result, ingredient_updates=ingredient_updates, expected_result=expected_result)

class MultipleFingerprintUpdateTasks(MultipleSimulationUpdateTasks):
    def __init__(self, multiple_simulation_tasks=None, name="update fingerprint", **kwargs):
        # Inherit simulation_project / mode / build_engine / concurrent from the inner
        # MultipleSimulationTasks so build_before_run has what it needs.
        if multiple_simulation_tasks is not None:
            kwargs.setdefault("simulation_project", multiple_simulation_tasks.simulation_project)
            kwargs.setdefault("mode", multiple_simulation_tasks.mode)
            kwargs.setdefault("build_engine", multiple_simulation_tasks.build_engine)
            kwargs.setdefault("concurrent", multiple_simulation_tasks.concurrent)
        super().__init__(name=name, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.multiple_simulation_tasks = multiple_simulation_tasks

    def run(self, **kwargs):
        # MultipleSimulationUpdateTasks.run_protected handles the optional build via
        # self.build / self.mode / self.build_engine; no need to duplicate that here.
        multiple_fingerprint_update_results = super().run(**kwargs)
        simulation_project = self.simulation_project or self.multiple_simulation_tasks.simulation_project
        correct_fingerprint_store = get_correct_fingerprint_store(simulation_project)
        for fingerprint_update_result in multiple_fingerprint_update_results.results:
            # An ERROR result changes nothing. Skipped tasks and exception-wrapped results
            # (plain SimulationUpdateTaskResult from the generic ERROR path) have no updates.
            if fingerprint_update_result.result == "ERROR":
                continue
            for ingredients, _, calculated_fingerprint in getattr(fingerprint_update_result, "ingredient_updates", []):
                # look the entry up by its key: a result from another process carries a copy
                simulation_task = fingerprint_update_result.task.simulation_task
                simulation_config = simulation_task.simulation_config
                key = dict(ingredients=ingredients, sim_time_limit=simulation_task.sim_time_limit, working_directory=simulation_config.working_directory,
                           ini_file=simulation_config.ini_file, config=simulation_config.config, run_number=simulation_task.run_number)
                stored_fingerprint_entry = correct_fingerprint_store.find_entry(**key)
                if stored_fingerprint_entry is None:
                    correct_fingerprint_store.insert_fingerprint(calculated_fingerprint.fingerprint, test_result="PASS", **key)
                else:
                    # the simulation finished, so an entry that expected another result now expects PASS
                    stored_fingerprint_entry["test_result"] = "PASS"
                    correct_fingerprint_store.update_fingerprint(calculated_fingerprint.fingerprint, **key)
        correct_fingerprint_store.write()
        return multiple_fingerprint_update_results

class FingerprintUpdateTaskResult(SimulationUpdateTaskResult):
    """
    The result of one FingerprintUpdateTask. ingredient_updates holds an (ingredients, stored entry or None,
    calculated Fingerprint or None) tuple for each recorded ingredient. The result is ERROR if a value was not
    calculated, else UPDATE if a stored value or expected result changes, else INSERT if a value is new, else KEEP.
    """
    def __init__(self, ingredient_updates=[], result=None, reason=None, **kwargs):
        if result is None:
            if not ingredient_updates or any(calculated_fingerprint is None for _, _, calculated_fingerprint in ingredient_updates):
                result = "ERROR"
                reason = reason or "Calculated fingerprint not found"
            elif any(entry is not None and (entry["fingerprint"] != calculated_fingerprint.fingerprint or entry["test_result"] != "PASS") for _, entry, calculated_fingerprint in ingredient_updates):
                result = "UPDATE"
            elif any(entry is None for _, entry, _ in ingredient_updates):
                result = "INSERT"
            else:
                result = "KEEP"
        super().__init__(result=result, reason=reason, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.ingredient_updates = ingredient_updates

    def get_description(self, complete_error_message=True, include_parameters=False, **kwargs):
        changes = []
        for ingredients, entry, calculated_fingerprint in self.ingredient_updates:
            if calculated_fingerprint is not None and (entry is None or entry["fingerprint"] != calculated_fingerprint.fingerprint):
                changes.append(str(calculated_fingerprint) + ("" if entry is None else " (was " + entry["fingerprint"] + ")"))
        return super().get_description(complete_error_message=complete_error_message, include_parameters=include_parameters, **kwargs) + \
               ("" if not changes else " " + ", ".join(changes))

    def __repr__(self):
        return "Fingerprint update result: " + self.get_description(include_parameters=True)

    def print_result(self, complete_error_message=True, output_stream=sys.stdout, **kwargs):
        print(self.get_description(complete_error_message=complete_error_message), file=output_stream)

class MultipleFingerprintUpdateTaskResults(MultipleUpdateTaskResults):
    def __init__(self, multiple_fingerprint_update_tasks, fingerprint_update_results, elapsed_wall_time=None, **kwargs):
        super().__init__(**kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.multiple_fingerprint_update_tasks = multiple_fingerprint_update_tasks
        self.fingerprint_update_results = fingerprint_update_results
        self.elapsed_wall_time = elapsed_wall_time
        self.num_different_results = 0
        self.num_keep = self.count_results("KEEP")
        self.num_insert = self.count_results("INSERT")
        self.num_update = self.count_results("UPDATE")
        self.num_error = self.count_results("ERROR")

    def __repr__(self):
        if len(self.fingerprint_update_results) == 1:
            return self.fingerprint_update_results[0].__repr__()
        else:
            details = self.get_details(exclude_result_filter="KEEP", include_parameters=True)
            return ("" if details.strip() == "" else "\nDetails:\n" + details + "\n\n") + \
                    "Fingerprint update summary: " + self.get_summary()

    def count_results(self, result):
        num = sum(e.result == result for e in self.fingerprint_update_results)
        if num != 0:
            self.num_different_results += 1
        return num

    def get_result_class_texts(self, result, color, num):
        texts = []
        if num != 0:
            texts += [(color + str(num) + " " + result + COLOR_RESET if num != 0 else "")]
        return texts

    def get_summary(self):
        if len(self.fingerprint_update_results) == 1:
            return self.fingerprint_update_results[0].get_description()
        else:
            texts = []
            if self.num_different_results != 1:
                texts.append(str(len(self.fingerprint_update_results)) + " TOTAL")
            texts += self.get_result_class_texts("KEEP", COLOR_GREEN, self.num_keep)
            texts += self.get_result_class_texts("INSERT", COLOR_YELLOW, self.num_insert)
            texts += self.get_result_class_texts("UPDATE", COLOR_YELLOW, self.num_update)
            texts += self.get_result_class_texts("ERROR", COLOR_RED, self.num_error)
            return ", ".join(texts) + (" in " + str(datetime.timedelta(seconds=self.elapsed_wall_time)) if self.elapsed_wall_time else "")

    def get_details(self, separator="\n  ", result_filter=None, exclude_result_filter=None, **kwargs):
        texts = []
        def matches_simulation_result(simulation_result, result):
            return simulation_result and simulation_result.result == result and \
                   matches_filter(result, result_filter, exclude_result_filter, True)
        for simulation_result in filter(lambda simulation_result: matches_simulation_result(simulation_result, "KEEP"), self.fingerprint_update_results):
            texts.append(simulation_result.get_description(**kwargs))
        for simulation_result in filter(lambda simulation_result: matches_simulation_result(simulation_result, "INSERT"), self.fingerprint_update_results):
            texts.append(simulation_result.get_description(**kwargs))
        for simulation_result in filter(lambda simulation_result: matches_simulation_result(simulation_result, "UPDATE"), self.fingerprint_update_results):
            texts.append(simulation_result.get_description(**kwargs))
        for simulation_result in filter(lambda simulation_result: matches_simulation_result(simulation_result, "ERROR"), self.fingerprint_update_results):
            texts.append(simulation_result.get_description(**kwargs))
        return "  " + separator.join(texts)

def get_update_correct_fingerprint_tasks(ingredients_list=None, sim_time_limit=None, stored_only=False, **kwargs):
    """
    Returns multiple fingerprint update tasks matching the provided filter criteria. The returned tasks can be run by
    calling the :py:meth:`run <opp_repl.common.task.MultipleTasks.run>` method. Each task records the ingredients
    of one run at one sim_time_limit with one simulation.

    Parameters:
        ingredients_list (List of string or None):
            The ingredients to record. None means every known ingredient.

        sim_time_limit (string or None):
            Record at this limit only. None means the stored limits of each run, or the limit of the ini file for
            a run without a stored fingerprint.

        stored_only (bool):
            When True, record only what the store holds: each stored run (iteration-variable run filters too) at
            each of its stored limits, for the ingredients that the store holds at that limit. When False, record
            every ingredient for every selected run, and insert the values that the store does not hold yet.

        kwargs (dict):
            The filter criteria parameters are inherited from the :py:meth:`get_simulation_tasks <opp_repl.simulation.task.get_simulation_tasks>` method.

    Returns (:py:class:`MultipleFingerprintUpdateTasks`):
        an object that contains a list of :py:class:`FingerprintUpdateTask` objects matching the provided filter criteria.
        The result can be run (and re-run) without providing additional parameters.
    """
    kwargs.setdefault("mode", "debug")
    if ingredients_list is None:
        ingredients_list = all_fingerprint_ingredients
    multiple_simulation_tasks = get_simulation_tasks(**kwargs)
    correct_fingerprint_store = get_correct_fingerprint_store(multiple_simulation_tasks.simulation_project)
    simulation_tasks = get_stored_simulation_tasks(multiple_simulation_tasks, correct_fingerprint_store) if stored_only else multiple_simulation_tasks.tasks
    fingerprint_update_tasks = []
    for simulation_task in simulation_tasks:
        simulation_config = simulation_task.simulation_config
        entries = [entry for entry in correct_fingerprint_store.filter_entries(ingredients=None, working_directory=simulation_config.working_directory, ini_file=simulation_config.ini_file,
                                                                               config=simulation_config.config, run_number=simulation_task.run_number)
                   if entry["ingredients"] in ingredients_list]
        if sim_time_limit is not None:
            sim_time_limits = [sim_time_limit]
        elif entries:
            sim_time_limits = sorted({entry["sim_time_limit"] for entry in entries}, key=lambda limit: (limit is not None, limit or ""))
        else:
            sim_time_limits = [simulation_task.sim_time_limit]
        for task_sim_time_limit in sim_time_limits:
            limit_entries = [entry for entry in entries if entry["sim_time_limit"] == task_sim_time_limit]
            task_ingredients_list = [ingredients for ingredients in ingredients_list if not stored_only or any(entry["ingredients"] == ingredients for entry in limit_entries)]
            if task_ingredients_list:
                expected_error = bool(limit_entries) and all(entry["test_result"] == "ERROR" for entry in limit_entries)
                fingerprint_update_tasks.append(FingerprintUpdateTask(simulation_task=copy_simulation_task(simulation_task, sim_time_limit=task_sim_time_limit),
                                                                      ingredients_list=task_ingredients_list, expected_error=expected_error))
    return MultipleFingerprintUpdateTasks(multiple_simulation_tasks, tasks=fingerprint_update_tasks, **kwargs)
get_update_correct_fingerprint_tasks.__signature__ = combine_signatures(get_update_correct_fingerprint_tasks, get_simulation_tasks)

def update_fingerprint_test_results(**kwargs):
    """
    Updates the stored correct fingerprints in the database for one or more fingerprint tests that match the provided
    filter criteria.

    Parameters:
        kwargs (dict):
            The filter criteria parameters are inherited from the :py:func:`get_update_correct_fingerprint_tasks` function.

    Returns (:py:class:`MultipleFingerprintUpdateTaskResults`):
        an object that contains a list of :py:class:`FingerprintUpdateTaskResult` objects. Each object describes the result of running one update task.
    """
    kwargs = apply_project_test_defaults("fingerprint", kwargs)
    multiple_fingerprint_update_tasks = get_update_correct_fingerprint_tasks(**kwargs)
    return multiple_fingerprint_update_tasks.run(**kwargs)
update_fingerprint_test_results.__signature__ = combine_signatures(update_fingerprint_test_results, get_update_correct_fingerprint_tasks)

def remove_correct_fingerprint(simulation_task, ingredients=None, **kwargs):
    simulation_config = simulation_task.simulation_config
    correct_fingerprint_store = get_correct_fingerprint_store(simulation_config.simulation_project)
    correct_fingerprint_store.remove_fingerprints(ingredients=ingredients, sim_time_limit=simulation_task.sim_time_limit,
                                                  working_directory=simulation_config.working_directory, ini_file=simulation_config.ini_file, config=simulation_config.config, run_number=simulation_task.run_number)

def remove_correct_fingerprints(**kwargs):
    _logger.info("Removing correct fingerprints")
    multiple_simulation_tasks = get_simulation_tasks(**kwargs)
    for simulation_task in multiple_simulation_tasks.tasks:
        remove_correct_fingerprint(simulation_task)
remove_correct_fingerprints.__signature__ = combine_signatures(remove_correct_fingerprints, get_simulation_tasks)

def remove_extra_correct_fingerprints(simulation_project=None, **kwargs):
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    correct_fingerprint_store = get_correct_fingerprint_store(simulation_project)
    for entry in correct_fingerprint_store.get_entries():
        found = False
        for simulation_config in get_all_simulation_configs(simulation_project):
            if simulation_config.working_directory == entry["working_directory"] and \
               simulation_config.ini_file == entry["ini_file"] and \
               simulation_config.config == entry["config"]:
                found = True
        if not found:
            correct_fingerprint_store.remove_entry(entry)
