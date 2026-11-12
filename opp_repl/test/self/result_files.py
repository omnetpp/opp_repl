#!/usr/bin/env python3
"""
Tests which result files the simulation tests make and remove.

The tests build and run no simulation. A stub takes the place of the run of the simulation task:
it records the arguments of the run, or it writes the result files and gives an error result.
"""

import importlib
import io
import os
import tempfile
import types
import unittest

from opp_repl.simulation.config import SimulationConfig
from opp_repl.simulation.project import SimulationProject
from opp_repl.test.sanitizer import SanitizerTestTask
from opp_repl.test.simulation import no_result_files_append_args
from opp_repl.test.smoke import SmokeTestTask
from opp_repl.test.statistical import StatisticalResultsUpdateTask, StatisticalTestTask

# the package attribute opp_repl.test.fingerprint is not this package after the star imports
FingerprintTestTask = importlib.import_module("opp_repl.test.fingerprint.task").FingerprintTestTask
speed_test_append_args = importlib.import_module("opp_repl.test.speed.task")._speed_test_append_args

def _make_simulation_config(root_folder):
    simulation_project = SimulationProject(name="demo", root_folder=root_folder)
    simulation_config = SimulationConfig(simulation_project, "simulations/demo", "omnetpp.ini", "General", num_runs=1)
    simulation_project.simulation_configs = [simulation_config]
    simulation_project._simulation_configs_freshness_key = simulation_project._compute_simulation_configs_freshness_key()
    return simulation_config

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
        for option in ["--record-eventlog=false", "--record-scalar-results=false", "--record-vector-results=false"]:
            self.assertIn(option, no_result_files_append_args)

    def test_the_options_do_not_name_the_result_files_of_a_manual_run(self):
        # OMNeT++ removes an old file with the name of a result file at the start of each run
        file_names = {option.split("=", 1)[0]: option.split("=", 1)[1] for option in no_result_files_append_args if "-file=" in option}
        self.assertEqual(sorted(file_names), ["--output-scalar-file", "--output-vector-file"])
        for file_name in file_names.values():
            self.assertTrue(file_name.startswith("${resultdir}/."))
            self.assertNotIn("${configname}", file_name)

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

class StatisticalResultFilesTestCase(unittest.TestCase):
    """The statistical test and update remove their result files also when the simulation stops."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.simulation_config = _make_simulation_config(self.folder.name)
        self.results_folder = os.path.join(self.folder.name, "simulations", "demo", "results")
        os.makedirs(self.results_folder)
        # a file of a manual run of the same config
        with open(os.path.join(self.results_folder, "General-#0.vec"), "w") as f:
            f.write("manual\n")

    def _run(self, task, result):
        def run_protected(**kwargs):
            # the simulation makes its result files and then stops
            for extension in ["sca", "vec", "vci"]:
                with open(os.path.join(self.results_folder, task.get_result_file_name(extension)), "w") as f:
                    f.write("partial\n")
            return types.SimpleNamespace(result=result, expected_result="DONE", expected=False, reason="stopped", subprocess_result=None)
        task.simulation_task.run_protected = run_protected
        task_result = task.run_protected(output_stream=io.StringIO())
        self.assertEqual(task_result.result, result)
        return sorted(os.listdir(self.results_folder))

    def test_statistical_test_after_an_error(self):
        self.assertEqual(self._run(StatisticalTestTask(simulation_config=self.simulation_config, run_number=0), "ERROR"), ["General-#0.vec"])

    def test_statistical_test_after_a_cancel(self):
        self.assertEqual(self._run(StatisticalTestTask(simulation_config=self.simulation_config, run_number=0), "CANCEL"), ["General-#0.vec"])

    def test_statistical_update_after_an_error(self):
        self.simulation_config.simulation_project.statistics_folder = "statistics"
        self.assertEqual(self._run(StatisticalResultsUpdateTask(simulation_config=self.simulation_config, run_number=0), "ERROR"), ["General-#0.vec"])

if __name__ == "__main__":
    unittest.main()
