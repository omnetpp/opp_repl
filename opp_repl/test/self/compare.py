#!/usr/bin/env python3
"""
Tests which output files a comparison of simulations keeps after the run.

The tests build and run no simulation. They make the compare tasks of two projects, write the
files that the two sides of a comparison write, and call the removal step of the comparison.
"""

import os
import tempfile
import types
import unittest

from opp_repl.simulation.compare import _get_comparison_simulation_tasks, _remove_output_files, get_compare_simulations_tasks
from opp_repl.simulation.config import SimulationConfig
from opp_repl.simulation.project import SimulationProject

def _make_project(name, root_folder, config_names):
    simulation_project = SimulationProject(name=name, root_folder=root_folder)
    # the configs are set here, thus the tests need no simulation project on the disk
    simulation_project.simulation_configs = [SimulationConfig(simulation_project, "simulations/demo", "omnetpp.ini", config_name, num_runs=1) for config_name in config_names]
    simulation_project._simulation_configs_freshness_key = simulation_project._compute_simulation_configs_freshness_key()
    return simulation_project

class CompareOutputTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def _make_results(self, verdicts, same_project=False):
        """Makes one comparison result for each verdict, with all output files of its two sides
        on the disk. A verdict is "IDENTICAL", "DIVERGENT" or None for a comparison that did not
        run its simulations."""
        config_names = [f"Config{index}" for index in range(len(verdicts))]
        project_1 = _make_project("demo", os.path.join(self.folder.name, "one"), config_names)
        project_2 = project_1 if same_project else _make_project("demo", os.path.join(self.folder.name, "two"), config_names)
        tasks_1, tasks_2 = _get_comparison_simulation_tasks(simulation_project_1=project_1, simulation_project_2=project_2, run_number=0)
        compare_tasks = get_compare_simulations_tasks(tasks_1, tasks_2, build=False).tasks
        results = []
        for compare_task, verdict in zip(compare_tasks, verdicts):
            multiple_task_results = None if verdict is None else types.SimpleNamespace(result="CANCEL", color="")
            result = compare_task.task_result_class(task=compare_task, multiple_task_results=multiple_task_results, result="SKIP" if verdict is None else "CANCEL")
            if verdict is not None:
                result.stdout_trajectory_comparison_result = verdict
                result._recompute_overall_result()
                self.assertEqual(result.result, verdict)
            for file_path in result.get_output_file_paths():
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w") as f:
                    f.write("output\n")
            results.append(result)
        return results

    def _remove(self, results, **kwargs):
        _remove_output_files(types.SimpleNamespace(results=results), **kwargs)
        return [[os.path.basename(file_path) for file_path in result.get_output_file_paths() if os.path.exists(file_path)] for result in results]

    def test_a_comparison_has_ten_output_files(self):
        result, = self._make_results(["IDENTICAL"])
        file_names = sorted(os.path.basename(file_path) for file_path in result.get_output_file_paths())
        self.assertEqual(file_names, sorted(f"Config0-#0-{side}.{extension}" for side in (1, 2) for extension in ("out", "elog", "sca", "vec", "vci")))

    def test_identical_removes_and_divergent_keeps(self):
        results = self._make_results(["IDENTICAL", "DIVERGENT"])
        identical_files, divergent_files = self._remove(results)
        self.assertEqual(identical_files, [])
        self.assertEqual(len(divergent_files), 10)
        self.assertTrue(results[0].output_files_removed)
        self.assertFalse(results[1].output_files_removed)

    def test_keep_output_all(self):
        identical_files, divergent_files = self._remove(self._make_results(["IDENTICAL", "DIVERGENT"]), keep_output="all")
        self.assertEqual(len(identical_files), 10)
        self.assertEqual(len(divergent_files), 10)

    def test_keep_output_none(self):
        identical_files, divergent_files = self._remove(self._make_results(["IDENTICAL", "DIVERGENT"]), keep_output="none")
        self.assertEqual(identical_files, [])
        self.assertEqual(divergent_files, [])

    def test_a_comparison_that_did_not_run_removes_no_file(self):
        # the files on the disk are those of an earlier run
        files, = self._remove(self._make_results([None]), keep_output="none")
        self.assertEqual(len(files), 10)

    def test_a_file_that_another_comparison_keeps_stays(self):
        # the two comparisons write the same files of the first side
        results = self._make_results(["IDENTICAL", "DIVERGENT"])
        results[0].task.multiple_simulation_tasks.tasks[0] = results[1].task.multiple_simulation_tasks.tasks[0]
        identical_files, divergent_files = self._remove(results)
        self.assertEqual(sorted(identical_files), sorted(f"Config1-#0-1.{extension}" for extension in ("out", "elog", "sca", "vec", "vci")))
        self.assertEqual(len(divergent_files), 10)
        self.assertFalse(os.path.exists(os.path.join(self.folder.name, "two", "simulations", "demo", "results", "Config0-#0-2.out")))

    def test_the_two_sides_can_be_in_one_project(self):
        files, = self._remove(self._make_results(["IDENTICAL"], same_project=True))
        self.assertEqual(files, [])
        self.assertEqual(os.listdir(os.path.join(self.folder.name, "one", "simulations", "demo", "results")), [])

    def test_recompare_needs_the_output_files(self):
        result, = self._make_results(["IDENTICAL"])
        self._remove([result])
        with self.assertRaisesRegex(Exception, "keep_output"):
            result.recompare(stdout_filter="some")

if __name__ == "__main__":
    unittest.main()
