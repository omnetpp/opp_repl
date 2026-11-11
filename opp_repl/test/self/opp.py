#!/usr/bin/env python3
"""
Tests which folders of the work directory the opp tests keep after a run.

The tests do not need OMNeT++: a stub takes the place of the opp_test command. The stub writes an
output file into the folder of the test, as opp_test does, and prints the result that the test case
asks for.
"""

import io
import os
import re
import tempfile
import types
import unittest
from unittest import mock

import opp_repl.test.opp
from opp_repl.test.opp import *

class _SimulationProject:
    """The part of a simulation project that an opp test task reads."""
    dynamic_libraries = ["Sample"]
    include_folders = []
    ned_folders = []

    def get_name(self):
        return "sample"

    def get_env(self, **kwargs):
        return dict(os.environ)

    def get_full_path(self, path):
        return path

    def get_library_folder_full_path(self):
        return "."

class OppTestOutputTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.simulation_project = _SimulationProject()
        self.opp_test_result = "PASS"
        patcher = mock.patch.object(opp_repl.test.opp, "run_command_with_logging", self._run_command)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run_command(self, args, cwd=None, **kwargs):
        """Takes the place of opp_test: the run step writes test.out into the folder that opp_test
        makes for the test, and prints the result."""
        if args[:2] == ["opp_test", "run"]:
            test_name = re.sub(r"[^A-Za-z0-9_]", "_", os.path.splitext(os.path.basename(args[args.index("-p") + 2]))[0])
            test_directory = os.path.join(cwd, args[args.index("-w") + 1], test_name)
            os.makedirs(test_directory, exist_ok=True)
            with open(os.path.join(test_directory, "test.out"), "w") as f:
                f.write("the complete output of the test\n")
            return types.SimpleNamespace(returncode=0, stdout=f"Aggregate result: {self.opp_test_result}\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    def _write_test_file(self, name="Sample", expected_result=None):
        # a %testprog test builds no binary, thus the stub is the only command that runs
        with open(os.path.join(self.folder.name, name + ".test"), "w") as f:
            f.write("%description:\nA sample test.\n%testprog: true\n")
            if expected_result:
                f.write(f"%# expected-result: {expected_result}\n")
        return name + ".test"

    def _make_task(self, **kwargs):
        return OppTestTask(self.simulation_project, self.folder.name, self._write_test_file(**kwargs), mode="release", task_result_class=TestTaskResult)

    def _run_task(self, opp_test_result, name="Sample", expected_result=None, **kwargs):
        """Runs one test and tells if the work folder has some content after the run."""
        self.opp_test_result = opp_test_result
        task = self._make_task(name=name, expected_result=expected_result)
        task_result = task.run(output_stream=io.StringIO(), **kwargs)
        return task_result, os.listdir(os.path.join(self.folder.name, "work")) != []

    def test_expected_result_removes_the_folder(self):
        task_result, has_output = self._run_task("PASS")
        self.assertEqual(task_result.result, "PASS")
        self.assertFalse(has_output)

    def test_unexpected_result_keeps_the_folder(self):
        task_result, has_output = self._run_task("FAIL")
        self.assertEqual(task_result.result, "FAIL")
        self.assertTrue(has_output)

    def test_expected_failure_removes_the_folder(self):
        task_result, has_output = self._run_task("FAIL", expected_result="FAIL")
        self.assertTrue(task_result.expected)
        self.assertFalse(has_output)

    def test_unexpected_pass_keeps_the_folder(self):
        task_result, has_output = self._run_task("PASS", expected_result="FAIL")
        self.assertFalse(task_result.expected)
        self.assertTrue(has_output)

    def test_test_name_with_other_characters(self):
        # opp_test changes such characters to "_" in the name of the folder
        task_result, has_output = self._run_task("PASS", name="sample-test.name")
        self.assertEqual(task_result.result, "PASS")
        self.assertFalse(has_output)

    def test_keep_output_all(self):
        task_result, has_output = self._run_task("PASS", keep_output="all")
        self.assertEqual(task_result.result, "PASS")
        self.assertTrue(has_output)

    def test_keep_output_none(self):
        task_result, has_output = self._run_task("FAIL", keep_output="none")
        self.assertEqual(task_result.result, "FAIL")
        self.assertFalse(has_output)

    def test_invalid_keep_output_is_an_error_and_keeps_the_folder(self):
        task_result, has_output = self._run_task("PASS", keep_output="some")
        self.assertEqual(task_result.result, "ERROR")
        self.assertIn("keep_output", task_result.error_message)
        self.assertTrue(has_output)

    def _run_suite(self, opp_test_result, **kwargs):
        self.opp_test_result = opp_test_result
        multiple_tasks = MultipleOppTestTasks(tasks=[self._make_task()], simulation_project=self.simulation_project, test_folder=self.folder.name,
                                              build=False, multiple_task_results_class=MultipleTestTaskResults)
        multiple_task_results = multiple_tasks.run(output_stream=io.StringIO(), **kwargs)
        return multiple_task_results, os.path.isdir(os.path.join(self.folder.name, "work"))

    def test_suite_removes_an_empty_work_folder(self):
        multiple_task_results, has_work_folder = self._run_suite("PASS")
        self.assertEqual(multiple_task_results.result, "PASS")
        self.assertFalse(has_work_folder)

    def test_suite_keeps_a_work_folder_with_a_test_in_it(self):
        multiple_task_results, has_work_folder = self._run_suite("FAIL")
        self.assertEqual(multiple_task_results.result, "FAIL")
        self.assertTrue(has_work_folder)

    def test_suite_passes_keep_output_to_the_tests(self):
        multiple_task_results, has_work_folder = self._run_suite("PASS", keep_output="all")
        self.assertEqual(multiple_task_results.result, "PASS")
        self.assertTrue(has_work_folder)

if __name__ == "__main__":
    unittest.main()
