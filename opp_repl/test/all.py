import logging


from opp_repl.test.chart import *
from opp_repl.test.feature import *
from opp_repl.test.fingerprint import *
from opp_repl.test.opp import *
from opp_repl.test.sanitizer import *
from opp_repl.test.simulation import *
from opp_repl.test.smoke import *
from opp_repl.test.speed import *
from opp_repl.test.statistical import *
from opp_repl.test.validation import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

def get_all_test_tasks(**kwargs):
    test_task_functions = [
                           get_chart_test_tasks,
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

def run_all_tests(**kwargs):
    return get_all_test_tasks(**kwargs).run(**kwargs)
