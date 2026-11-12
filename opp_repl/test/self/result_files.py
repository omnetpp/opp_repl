#!/usr/bin/env python3
"""
Tests which result files the simulation tests make and remove.

The tests build and run no simulation. A stub takes the place of the run of the simulation task:
it records the arguments of the run.
"""

import importlib
import io
import types
import unittest

from opp_repl.test.sanitizer import SanitizerTestTask
from opp_repl.test.simulation import no_result_files_append_args
from opp_repl.test.smoke import SmokeTestTask

# the package attribute opp_repl.test.fingerprint is not this package after the star imports
FingerprintTestTask = importlib.import_module("opp_repl.test.fingerprint.task").FingerprintTestTask
speed_test_append_args = importlib.import_module("opp_repl.test.speed.task")._speed_test_append_args

class NoResultFilesTestCase(unittest.TestCase):
    """The tests that read only the stdout and stderr of the simulation turn the result files off."""

    def _run(self, test_task_class, **kwargs):
        run_kwargs = {}
        def run_protected(**kwargs):
            run_kwargs.update(kwargs)
            return types.SimpleNamespace(result="DONE", expected_result="DONE", expected=True, reason=None, subprocess_result=types.SimpleNamespace(stderr=""))
        simulation_task = types.SimpleNamespace(simulation_config=types.SimpleNamespace(user_interface=None), user_interface="Cmdenv", run_protected=run_protected)
        task_result = test_task_class(simulation_task=simulation_task).run_protected(output_stream=io.StringIO(), **kwargs)
        self.assertEqual(task_result.result, "PASS")
        return run_kwargs["append_args"]

    def test_the_options_turn_off_the_two_result_files_and_the_eventlog(self):
        self.assertEqual(sorted(no_result_files_append_args), ["--record-eventlog=false", "--record-scalar-results=false", "--record-vector-results=false"])

    def test_smoke_test(self):
        self.assertEqual(self._run(SmokeTestTask), no_result_files_append_args)

    def test_sanitizer_test(self):
        self.assertEqual(self._run(SanitizerTestTask), no_result_files_append_args)

    def test_the_arguments_of_the_caller_come_after_the_options(self):
        self.assertEqual(self._run(SmokeTestTask, append_args=["--some-option=1"]), no_result_files_append_args + ["--some-option=1"])

    def test_fingerprint_test(self):
        append_args = FingerprintTestTask.get_append_args(None, None, "abcd-1234/tplx")
        self.assertEqual(append_args, ["--fingerprint", "abcd-1234/tplx", *no_result_files_append_args])

    def test_speed_test(self):
        for option in no_result_files_append_args:
            self.assertIn(option, speed_test_append_args)

if __name__ == "__main__":
    unittest.main()
