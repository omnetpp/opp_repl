"""
The check of a selection on each push (check V4 of the test selection plan of opp_repl,
``plan/pending/test-selection.md``, section 10): a push to ``master`` runs all tests, and each test
whose result differs from the result of the previous push run must be in the selection of the change
between the two pushes. A test that the selection misses is a defect of a rule or an assumption.
"""

import json
import logging

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

def read_test_outcomes(file_name):
    """Returns ``{test map key: (result, expected)}`` of a result file of a run command (``--result-file``)."""
    with open(file_name) as f:
        data = json.load(f)
    outcomes = {}
    def walk(value):
        if isinstance(value, dict):
            if value.get("test_map_key"):
                outcomes[value["test_map_key"]] = (value.get("result"), value.get("expected"))
            for child in value.get("results") or []:
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(data)
    return outcomes

def check_test_selection(simulation_project=None, changes=None, map_folder=None, result_files=[], previous_result_files=[], kind="fingerprint", ignore_environment=False):
    """
    Checks a selection against the results of two full runs: the tests whose result changed from the
    previous result files to the result files must be selected for *changes* with the map of the
    previous run. Returns the keys of the tests that the selection misses (an empty list if none).
    """
    from opp_repl.test.test_map.select import select_tests
    outcomes = {}
    for file_name in result_files:
        outcomes.update(read_test_outcomes(file_name))
    previous = {}
    for file_name in previous_result_files:
        previous.update(read_test_outcomes(file_name))
    changed = sorted(key for key, outcome in outcomes.items() if key in previous and previous[key] != outcome)
    selection = select_tests(simulation_project=simulation_project, changes=changes, map_folder=map_folder, kinds=[kind], ignore_environment=ignore_environment)
    missed = [key for key in changed if not selection.is_selected(kind, key)]
    _logger.info(f"{len(changed)} of {len(outcomes)} {kind} tests changed their result, the selection of {selection.changes.describe()} missed {len(missed)}")
    for key in missed:
        _logger.error(f"The selection missed {key}: {previous[key]} before, {outcomes[key]} now")
    return missed
