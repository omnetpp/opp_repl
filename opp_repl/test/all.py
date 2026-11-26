import importlib.util
import logging

from opp_repl.test.feature import *
from opp_repl.test.fingerprint import *
from opp_repl.test.opp import *
from opp_repl.test.sanitizer import *
from opp_repl.test.simulation import *
from opp_repl.test.smoke import *
from opp_repl.test.speed import *
from opp_repl.test.statistical import *

if importlib.util.find_spec("matplotlib"):
    from opp_repl.test.chart import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

def get_all_test_tasks(**kwargs):
    test_task_functions = [
                           *([get_chart_test_tasks] if importlib.util.find_spec("matplotlib") else []),
                           get_feature_test_tasks,
                           get_fingerprint_test_tasks,
                           get_sanitizer_test_tasks,
                           get_smoke_test_tasks,
                           get_speed_test_tasks,
                           get_statistical_test_tasks,
                          ]
    test_tasks = []
    for test_task_function in test_task_functions:
        multiple_test_tasks = test_task_function(**dict(kwargs, pass_keyboard_interrupt=True))
        if multiple_test_tasks.tasks:
            test_tasks.append(multiple_test_tasks)
    return MultipleTestTasks(tasks=test_tasks, **dict(kwargs, name="test group", start=None, end=None, concurrent=False))
get_all_test_tasks.__signature__ = combine_signatures(get_all_test_tasks, get_simulation_tasks)

def run_all_tests(changes=None, test_map=None, ignore_environment=False, **kwargs):
    """
    Runs the tests of all kinds. With *changes*, only the tests whose outcome the change can change
    run (see :py:func:`opp_repl.test.fingerprint.task.run_fingerprint_tests`); a kind of test that the
    test map does not hold runs all its tests.
    """
    multiple_test_tasks = get_all_test_tasks(**kwargs)
    if changes:
        # lazy: the test map imports the coverage module, which imports the simulation modules
        from opp_repl.test.test_map.select import get_test_kind, get_test_selection_for_run, select_test_tasks
        test_selection = get_test_selection_for_run(kwargs.get("simulation_project"), changes, test_map=test_map, ignore_environment=ignore_environment)
        for kind_test_tasks in multiple_test_tasks.tasks:
            select_test_tasks(get_test_kind(kind_test_tasks), kind_test_tasks, test_selection)
    return multiple_test_tasks.run(**kwargs)
run_all_tests.__signature__ = combine_signatures(run_all_tests, get_all_test_tasks)
