#!/usr/bin/env python3
"""
Tests how the fingerprint test and the fingerprint update treat a run that a time limit stops.

The tests build and run no simulation. The output of Cmdenv is a copy of real output; a stub takes the place
of the run of the simulation task.
"""

import importlib
import io
import types
import unittest

from opp_repl.simulation.fingerprint import Fingerprint
from opp_repl.simulation.task import SimulationTaskResult

# the package attribute opp_repl.test.fingerprint is not this package after the star imports
fingerprint_task = importlib.import_module("opp_repl.test.fingerprint.task")

# the end of a run of examples/mrp LargeNetworkWithTraffic -r 15 with --cpu-time-limit=2s
cpu_time_limit_stdout = """
<!> CPU time limit reached -- at t=0.710039s, event #1167360

Calling finish() at end of Run #15...

<!> Fingerprint mismatch! calculated: b1b6-a675/tplx, expected: e432-18b7/tplx
"""

sim_time_limit_stdout = """
<!> Simulation time limit reached -- at t=2.2s, event #4634112

Calling finish() at end of Run #15...

<!> Fingerprint mismatch! calculated: b1b6-a675/tplx, expected: e432-18b7/tplx
"""

def _make_simulation_task_result(stdout):
    return SimulationTaskResult(subprocess_result=types.SimpleNamespace(stdout=stdout, stderr="", returncode=0))

def _make_test_task():
    return fingerprint_task.FingerprintTestTask(simulation_task=types.SimpleNamespace(), sim_time_limit="2.2s", ingredients="tplx",
                                                fingerprint=Fingerprint("e432-18b7", "tplx"), test_result="PASS")

class TimeLimitTestCase(unittest.TestCase):
    def test_the_simulation_result_keeps_the_message_of_the_time_limit(self):
        simulation_task_result = _make_simulation_task_result(cpu_time_limit_stdout)
        self.assertEqual(simulation_task_result.time_limit_reached, "CPU time limit reached")
        self.assertEqual(simulation_task_result.last_simulation_time, "0.710039s")
        self.assertEqual(simulation_task_result.last_event_number, 1167360)
        simulation_task_result = _make_simulation_task_result(sim_time_limit_stdout)
        self.assertEqual(simulation_task_result.time_limit_reached, "Simulation time limit reached")
        self.assertEqual(simulation_task_result.last_simulation_time, "2.2s")

    def test_a_cpu_time_limit_gives_an_error_and_no_mismatch(self):
        test_result = _make_test_task().check_simulation_task_result(_make_simulation_task_result(cpu_time_limit_stdout))
        self.assertEqual(test_result.result, "ERROR")
        self.assertEqual(test_result.reason, "CPU time limit reached at t=0.710039s")
        self.assertIsNone(test_result.calculated_fingerprint)
        self.assertFalse(test_result.fingerprint_mismatch)
        self.assertNotIn("calculated", test_result.get_description())
        self.assertIn("the run stopped before its sim-time-limit 2.2s", test_result.get_description())
        self.assertNotIn("<No error message>", test_result.get_description())

    def test_a_realtime_limit_gives_an_error(self):
        stdout = cpu_time_limit_stdout.replace("CPU time limit reached", "Realtime limit reached")
        test_result = _make_test_task().check_simulation_task_result(_make_simulation_task_result(stdout))
        self.assertEqual(test_result.result, "ERROR")
        self.assertEqual(test_result.reason, "Realtime limit reached at t=0.710039s")

    def test_the_sim_time_limit_still_gives_a_mismatch(self):
        test_result = _make_test_task().check_simulation_task_result(_make_simulation_task_result(sim_time_limit_stdout))
        self.assertEqual(test_result.result, "FAIL")
        self.assertEqual(test_result.reason, "Fingerprint mismatch")
        self.assertTrue(test_result.fingerprint_mismatch)
        self.assertIn("calculated b1b6-a675/tplx (correct e432-18b7/tplx)", test_result.get_description())

    def test_a_cpu_time_limit_gives_an_update_error_that_stores_nothing(self):
        simulation_task = types.SimpleNamespace(sim_time_limit="2.2s", run_protected=lambda **kwargs: _make_simulation_task_result(cpu_time_limit_stdout))
        update_task = fingerprint_task.FingerprintUpdateTask(simulation_task=simulation_task, ingredients_list=["tplx"])
        update_result = update_task.run_protected(output_stream=io.StringIO())
        self.assertEqual(update_result.result, "ERROR")
        self.assertEqual(update_result.reason, "CPU time limit reached at t=0.710039s")
        self.assertEqual(update_result.error_message, "the run stopped before its sim-time-limit 2.2s")
        self.assertEqual(update_result.ingredient_updates, [])
