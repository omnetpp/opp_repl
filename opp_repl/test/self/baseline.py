#!/usr/bin/env python3
"""
Tests the checkout of the baseline repository of a test kind, and the report of a checkout that is
not at the commit that the simulation project declares.

The tests make small git repositories in a temporary folder. They build and run no simulation.
"""

import logging
import os
import subprocess
import tempfile
import unittest

import opp_repl.test.baseline as baseline_module
from opp_repl.simulation.project import SimulationProject
from opp_repl.test.baseline import check_test_baseline, checkout_test_baseline, checkout_test_baselines, get_test_baseline_commit, get_test_baseline_kinds, get_test_baseline_url

def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

class BaselineTestCase(unittest.TestCase):
    def setUp(self):
        # the test output has no use for the line on each clone and each checkout
        self.addCleanup(baseline_module._logger.setLevel, baseline_module._logger.level)
        baseline_module._logger.setLevel(logging.WARNING)
        self.temporary_folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_folder.cleanup)
        folder = os.path.realpath(self.temporary_folder.name)
        # the baseline repository: two commits on its branch, and one more that only a pull request head holds
        self.repository = os.path.join(folder, "statistics.git")
        os.makedirs(self.repository)
        _git(self.repository, "init", "-q", "-b", "master", ".")
        # GitHub gives a commit that a ref can reach to a fetch by its hash; a plain repository needs this option for that
        _git(self.repository, "config", "uploadpack.allowAnySHA1InWant", "true")
        self.first_commit = self._commit("first", "1\n")
        self.second_commit = self._commit("second", "2\n")
        _git(self.repository, "checkout", "-q", "--detach")
        self.pull_request_commit = self._commit("pull request", "3\n")
        _git(self.repository, "update-ref", "refs/pull/1/head", self.pull_request_commit)
        _git(self.repository, "checkout", "-q", "master")
        self.project_root = os.path.join(folder, "demo")
        os.makedirs(self.project_root)
        self.checkout_folder = os.path.join(self.project_root, "statistics")

    def _commit(self, message, content):
        with open(os.path.join(self.repository, "omnetpp.ini-General-#0.sca"), "w") as f:
            f.write(content)
        _git(self.repository, "add", "-A")
        _git(self.repository, "commit", "-q", "-m", message)
        return _git(self.repository, "rev-parse", "HEAD")

    def _make_project(self, ref=None, **test_parameters):
        baseline = {"repository": "file://" + self.repository, "folder": "statistics"}
        if ref:
            baseline["ref"] = ref
        return SimulationProject(name="demo", root_folder=self.project_root, test_parameters={"statistical": {"baseline": baseline}, **test_parameters})

    def _read_stored_result(self):
        with open(os.path.join(self.checkout_folder, "omnetpp.ini-General-#0.sca")) as f:
            return f.read()

    def test_a_new_clone_is_at_the_declared_commit(self):
        commit = checkout_test_baseline("statistical", simulation_project=self._make_project(ref=self.first_commit))
        self.assertEqual(commit, self.first_commit)
        self.assertEqual(self._read_stored_result(), "1\n")

    def test_a_new_clone_at_the_head_of_the_branch_has_its_files(self):
        # a clone with no checkout has its HEAD at this commit already, and the files must still come
        checkout_test_baseline("statistical", simulation_project=self._make_project(ref=self.second_commit))
        self.assertEqual(self._read_stored_result(), "2\n")

    def test_a_clone_moves_to_a_new_declared_commit(self):
        checkout_test_baseline("statistical", simulation_project=self._make_project(ref=self.first_commit))
        third_commit = self._commit("third", "4\n")
        commit = checkout_test_baseline("statistical", simulation_project=self._make_project(ref=third_commit))
        self.assertEqual(commit, third_commit)
        self.assertEqual(self._read_stored_result(), "4\n")

    def test_a_commit_that_only_a_pull_request_holds_is_fetched_by_its_hash(self):
        checkout_test_baseline("statistical", simulation_project=self._make_project(ref=self.first_commit))
        self.assertIsNone(baseline_module._find_commit(self.checkout_folder, self.pull_request_commit))
        commit = checkout_test_baseline("statistical", simulation_project=self._make_project(ref=self.pull_request_commit))
        self.assertEqual(commit, self.pull_request_commit)
        self.assertEqual(self._read_stored_result(), "3\n")

    def test_a_checkout_at_the_declared_commit_stays_on_its_branch(self):
        _git(self.project_root, "clone", "-q", "file://" + self.repository, "statistics")
        checkout_test_baseline("statistical", simulation_project=self._make_project(ref=self.second_commit))
        self.assertEqual(_git(self.checkout_folder, "symbolic-ref", "--short", "HEAD"), "master")

    def test_a_branch_name_gives_the_head_of_the_branch(self):
        checkout_test_baseline("statistical", simulation_project=self._make_project(ref="master"))
        third_commit = self._commit("third", "4\n")
        commit = checkout_test_baseline("statistical", simulation_project=self._make_project(ref="master"))
        self.assertEqual(commit, third_commit)

    def test_no_declared_commit_gives_the_default_branch_and_keeps_a_clone(self):
        simulation_project = self._make_project()
        self.assertEqual(checkout_test_baseline("statistical", simulation_project=simulation_project), self.second_commit)
        self._commit("third", "4\n")
        self.assertEqual(checkout_test_baseline("statistical", simulation_project=simulation_project), self.second_commit)

    def test_a_local_change_stops_the_checkout(self):
        checkout_test_baseline("statistical", simulation_project=self._make_project(ref=self.first_commit))
        with open(os.path.join(self.checkout_folder, "omnetpp.ini-General-#0.sca"), "w") as f:
            f.write("my work\n")
        with self.assertRaises(RuntimeError):
            checkout_test_baseline("statistical", simulation_project=self._make_project(ref=self.second_commit))
        self.assertEqual(self._read_stored_result(), "my work\n")
        self.assertEqual(_git(self.checkout_folder, "rev-parse", "HEAD"), self.first_commit)

    def test_a_folder_with_files_and_no_repository_is_an_error(self):
        os.makedirs(self.checkout_folder)
        with open(os.path.join(self.checkout_folder, "notes.txt"), "w") as f:
            f.write("notes\n")
        with self.assertRaises(RuntimeError):
            checkout_test_baseline("statistical", simulation_project=self._make_project(ref=self.first_commit))
        self.assertEqual(os.listdir(self.checkout_folder), ["notes.txt"])

    def test_a_kind_with_no_baseline_is_an_error(self):
        with self.assertRaises(ValueError):
            checkout_test_baseline("chart", simulation_project=self._make_project(ref=self.first_commit))

    def test_all_declared_kinds_are_checked_out(self):
        simulation_project = self._make_project(ref=self.first_commit, chart={"baseline": {"repository": "file://" + self.repository, "ref": self.second_commit, "folder": "media"}}, smoke={"defaults": {"run_number": 0}})
        self.assertEqual(get_test_baseline_kinds(simulation_project), ["statistical", "chart"])
        self.assertEqual(checkout_test_baselines(simulation_project=simulation_project), {"statistical": self.first_commit, "chart": self.second_commit})
        self.assertEqual(get_test_baseline_commit("chart", simulation_project=simulation_project), self.second_commit)

    def test_the_check_is_silent_at_the_declared_commit(self):
        simulation_project = self._make_project(ref=self.first_commit)
        checkout_test_baseline("statistical", simulation_project=simulation_project)
        with self.assertNoLogs(baseline_module._logger, level=logging.WARNING):
            self.assertEqual(check_test_baseline("statistical", simulation_project=simulation_project), self.first_commit)

    def test_the_check_reports_another_commit_and_changes_nothing(self):
        checkout_test_baseline("statistical", simulation_project=self._make_project(ref=self.first_commit))
        with self.assertLogs(baseline_module._logger, level=logging.WARNING) as logs:
            commit = check_test_baseline("statistical", simulation_project=self._make_project(ref=self.second_commit))
        self.assertEqual(commit, self.first_commit)
        self.assertIn(self.second_commit, logs.output[0])
        self.assertEqual(_git(self.checkout_folder, "rev-parse", "HEAD"), self.first_commit)

    def test_the_check_reports_a_missing_checkout(self):
        with self.assertLogs(baseline_module._logger, level=logging.WARNING) as logs:
            self.assertIsNone(check_test_baseline("statistical", simulation_project=self._make_project(ref=self.first_commit)))
        self.assertIn("is not checked out", logs.output[0])

    def test_the_check_reports_a_checkout_that_git_cannot_read(self):
        # a worktree whose repository is not there has a .git file and no commit that git can read
        os.makedirs(self.checkout_folder)
        with open(os.path.join(self.checkout_folder, ".git"), "w") as f:
            f.write("gitdir: /nonexistent/repository/.git/worktrees/statistics\n")
        with self.assertLogs(baseline_module._logger, level=logging.WARNING) as logs:
            self.assertIsNone(check_test_baseline("statistical", simulation_project=self._make_project(ref=self.first_commit)))
        self.assertIn("Cannot read the commit", logs.output[0])

    def test_the_check_reads_the_checkout_of_the_baseline_project(self):
        # a comparison between commits keeps the stored results in the project of the user
        simulation_project = self._make_project(ref=self.first_commit)
        checkout_test_baseline("statistical", simulation_project=simulation_project)
        other_root = os.path.join(os.path.dirname(self.project_root), "demo-other")
        os.makedirs(other_root)
        other_project = SimulationProject(name="demo", root_folder=other_root, test_parameters=simulation_project.test_parameters)
        self.assertEqual(check_test_baseline("statistical", simulation_project=other_project, baseline_simulation_project=simulation_project), self.first_commit)

    def test_the_check_is_silent_for_a_kind_with_no_baseline(self):
        with self.assertNoLogs(baseline_module._logger, level=logging.WARNING):
            self.assertIsNone(check_test_baseline("chart", simulation_project=self._make_project(ref=self.first_commit)))

    def test_the_url_of_a_repository(self):
        self.assertEqual(get_test_baseline_url("inet-framework/statistics"), "https://github.com/inet-framework/statistics.git")
        self.assertEqual(get_test_baseline_url("git@github.com:inet-framework/statistics.git"), "git@github.com:inet-framework/statistics.git")
        self.assertEqual(get_test_baseline_url("file:///tmp/statistics"), "file:///tmp/statistics")

if __name__ == "__main__":
    unittest.main()
