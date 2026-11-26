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
from opp_repl.test.baseline import check_test_baseline, checkout_test_baseline, checkout_test_baselines, get_test_baseline_commit, get_test_baseline_kinds, get_test_baseline_url, resolve_test_baseline

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

class TrailerBaselineTestCase(unittest.TestCase):
    """
    The trailer form: a project commit names its baseline commit in a trailer, and a mark on the default
    branch of the baseline repository names the baseline of each landed project commit. The fixture lands
    series as the landing job does: the project commit gets a new hash (as "Rebase and merge" gives), and
    the baseline commits land by a fast-forward or by a rebase, with a mark after them.
    """

    def setUp(self):
        self.addCleanup(baseline_module._logger.setLevel, baseline_module._logger.level)
        baseline_module._logger.setLevel(logging.WARNING)
        self.temporary_folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_folder.cleanup)
        self.folder = os.path.realpath(self.temporary_folder.name)
        self.repository = os.path.join(self.folder, "statistics.git")
        os.makedirs(self.repository)
        _git(self.repository, "init", "-q", "-b", "master", ".")
        _git(self.repository, "config", "uploadpack.allowAnySHA1InWant", "true")
        self.first = self._baseline_commit("first", {"a.sca": "1\n", "b.sca": "1\n"})
        self.project_root = os.path.join(self.folder, "demo")
        os.makedirs(self.project_root)
        _git(self.project_root, "init", "-q", "-b", "master", ".")
        self._write_project_file(".gitignore", "statistics/\n")
        self._write_opp_file(ref=self.first)
        self.old = self._project_commit("old: the ref form", files=[".gitignore", "demo.opp"])
        self._write_opp_file()
        self.switch = self._project_commit("switch: the trailer form", files=["demo.opp"])
        self.checkout_folder = os.path.join(self.project_root, "statistics")

    def _write_project_file(self, name, content):
        with open(os.path.join(self.project_root, name), "w") as f:
            f.write(content)

    def _get_baseline_entry(self, ref=None):
        entry = {"repository": "file://" + self.repository, "folder": "statistics"}
        entry.update({"ref": ref} if ref else {"trailer": "Statistical-Baseline"})
        return entry

    def _write_opp_file(self, ref=None):
        self._write_project_file("demo.opp", f"SimulationProject(test_parameters={{'statistical': {{'baseline': {self._get_baseline_entry(ref)!r}}}}})\n")

    def _make_project(self):
        return SimulationProject(name="demo", root_folder=self.project_root, test_parameters={"statistical": {"baseline": self._get_baseline_entry()}})

    def _project_commit(self, message, pin=None, files=None, branch=None):
        if branch:
            _git(self.project_root, "checkout", "-q", branch)
        if files is None:
            name = "source-" + message.split(":")[0].replace(" ", "-") + ".txt"
            self._write_project_file(name, message + "\n")
            files = [name]
        _git(self.project_root, "add", *files)
        _git(self.project_root, "commit", "-q", "-m", message + (f"\n\nStatistical-Baseline: {pin}" if pin else ""))
        return _git(self.project_root, "rev-parse", "HEAD")

    def _baseline_commit(self, message, files, start=None):
        if start:
            _git(self.repository, "checkout", "-q", "--detach", start)
        for name, content in files.items():
            with open(os.path.join(self.repository, name), "w") as f:
                f.write(content)
        _git(self.repository, "add", *files)
        _git(self.repository, "commit", "-q", "-m", message)
        commit = _git(self.repository, "rev-parse", "HEAD")
        _git(self.repository, "checkout", "-q", "master")
        return commit

    def _mark(self, pairs):
        _git(self.repository, "checkout", "-q", "master")
        trailers = "".join(f"Baseline-Of: {project} {baseline}\n" for project, baseline in pairs)
        _git(self.repository, "commit", "-q", "--allow-empty", "-m", f"Baseline of demo {pairs[-1][0][:10]}\n\n{trailers}")
        return _git(self.repository, "rev-parse", "HEAD")

    def _land_project_commit(self, commit):
        """Lands one project commit on master with a new hash, as "Rebase and merge" does."""
        _git(self.project_root, "checkout", "-q", "master")
        # a new committer date gives a new hash also when the parent stays the same
        subprocess.run(["git", "-c", "user.name=lander", "-c", "user.email=lander@example.com", "cherry-pick", commit], cwd=self.project_root, check=True, capture_output=True, env={**os.environ, "GIT_COMMITTER_DATE": "2030-01-01T00:00:00+0000"})
        return _git(self.project_root, "rev-parse", "HEAD")

    def _start_series(self, name, start="master"):
        _git(self.project_root, "checkout", "-q", "-b", name, start)

    def _resolve(self, project_commit, **kwargs):
        if not os.path.exists(self.checkout_folder):
            _git(self.project_root, "clone", "-q", "--no-checkout", "file://" + self.repository, "statistics")
        return resolve_test_baseline("statistical", simulation_project=self._make_project(), project_commit=project_commit, **kwargs)

    def _read_tree(self, commit):
        return {name: _git(self.repository if baseline_module._find_commit(self.repository, commit) else self.checkout_folder, "show", f"{commit}:{name}") for name in ("a.sca", "b.sca")}

    def _setup_marked_master(self):
        # the switch lands, and the first cause commit after it gets a mark; the series start on the mark
        self.mark0 = self._mark([(self.switch, self.first)])

    def test_before_the_first_mark_the_old_ref_is_the_baseline(self):
        test_baseline = self._resolve(self.switch)
        self.assertEqual(test_baseline.commit, self.first)
        self.assertIsNone(test_baseline.marked)

    def test_a_mark_gives_the_baseline_of_a_commit_and_its_descendants(self):
        self._setup_marked_master()
        after = self._project_commit("after: no pin")
        test_baseline = self._resolve(after)
        self.assertEqual((test_baseline.marked, test_baseline.master, test_baseline.commit), (self.switch, self.first, self.first))

    def test_a_pin_on_a_branch_that_starts_on_the_mark_needs_no_rebase(self):
        self._setup_marked_master()
        pin = self._baseline_commit("a moves", {"a.sca": "2\n"}, start=self.mark0)
        self._start_series("topic/a")
        cause = self._project_commit("a: moves a", pin=pin)
        self._project_commit("a2: after the cause commit")
        test_baseline = self._resolve("topic/a")
        self.assertEqual((test_baseline.cause, test_baseline.pin, test_baseline.commit, test_baseline.rebased), (cause, pin, pin, False))

    def _land_first_series_by_fast_forward(self):
        self._setup_marked_master()
        self.pin_a = self._baseline_commit("a moves", {"a.sca": "2\n"}, start=self.mark0)
        self._start_series("topic/a")
        self.cause_a = self._project_commit("a: moves a", pin=self.pin_a)
        self._start_series("topic/b", start=self.switch)
        self.pin_b = self._baseline_commit("b moves", {"b.sca": "2\n"}, start=self.mark0)
        self.cause_b = self._project_commit("b: moves b", pin=self.pin_b)
        self.landed_a = self._land_project_commit(self.cause_a)
        _git(self.repository, "merge", "-q", "--ff-only", self.pin_a)
        self.mark_a = self._mark([(self.landed_a, self.pin_a)])

    def test_after_a_fast_forward_the_pin_is_the_baseline_of_the_landed_commit(self):
        self._land_first_series_by_fast_forward()
        self.assertEqual(self._resolve(self.landed_a).commit, self.pin_a)
        # the commit before the landing keeps its baseline: its pin is on the default branch now
        self.assertEqual(self._resolve(self.cause_a).commit, self.pin_a)

    def test_the_merge_ref_of_a_second_series_gets_the_rebased_branch(self):
        self._land_first_series_by_fast_forward()
        _git(self.project_root, "checkout", "-q", "--detach", "master")
        _git(self.project_root, "merge", "-q", "--no-ff", "-m", "Merge topic/b into master", "topic/b")
        merge = _git(self.project_root, "rev-parse", "HEAD")
        test_baseline = self._resolve(merge)
        self.assertEqual((test_baseline.base, test_baseline.master, test_baseline.pin, test_baseline.rebased), (self.landed_a, self.pin_a, self.pin_b, True))
        self.assertEqual(self._read_tree(test_baseline.commit), {"a.sca": "2", "b.sca": "2"})
        # the rebased commit keeps the author, the committer, the dates and the message, so another clone makes the same commit
        other = os.path.join(self.folder, "other")
        _git(self.folder, "clone", "-q", "file://" + self.repository, other)
        _git(other, "fetch", "-q", "origin", self.pin_b)
        commit, rebased = baseline_module.rebase_baseline_branch(other, self.pin_b, self.pin_a, "origin/master")
        self.assertEqual((commit, rebased), (test_baseline.commit, True))
        self.assertEqual(_git(other, "log", "-1", "--format=%an %s", commit), "test b moves")
        # the series itself keeps the baseline of its base, for the attribution runs
        self.assertEqual(self._resolve(self.cause_b).commit, self.pin_b)

    def test_an_overlap_with_the_default_branch_is_an_error(self):
        self._land_first_series_by_fast_forward()
        pin = self._baseline_commit("a moves again", {"a.sca": "3\n"}, start=self.mark0)
        self._start_series("topic/c", start=self.switch)
        self._project_commit("c: moves a again", pin=pin)
        _git(self.project_root, "checkout", "-q", "--detach", "master")
        _git(self.project_root, "merge", "-q", "--no-ff", "-m", "Merge topic/c into master", "topic/c")
        with self.assertRaisesRegex(RuntimeError, "overlaps .* both change a.sca"):
            self._resolve("HEAD")

    def test_after_a_rebase_the_mark_gives_the_rebased_commit(self):
        self._land_first_series_by_fast_forward()
        landed_b = self._land_project_commit(self.cause_b)
        # the landing job rebases the step with its own committer, so its commit differs from a local rebase
        subprocess.run(["git", "-c", "user.name=lander", "-c", "user.email=lander@example.com", "cherry-pick", self.pin_b], cwd=self.repository, check=True, capture_output=True)
        rebased_b = _git(self.repository, "rev-parse", "HEAD")
        self._mark([(landed_b, rebased_b)])
        self.assertEqual(self._resolve(landed_b).commit, rebased_b)
        self.assertEqual(self._read_tree(rebased_b), {"a.sca": "2", "b.sca": "2"})

    def test_one_mark_names_two_steps_of_a_series(self):
        self._setup_marked_master()
        pin_1 = self._baseline_commit("a moves", {"a.sca": "2\n"}, start=self.mark0)
        pin_2 = self._baseline_commit("b moves", {"b.sca": "2\n"}, start=pin_1)
        self._start_series("topic/d")
        self._project_commit("d1: moves a", pin=pin_1)
        self._project_commit("d2: moves b", pin=pin_2)
        landed_1 = self._land_project_commit("topic/d~1")
        landed_2 = self._land_project_commit("topic/d")
        _git(self.repository, "merge", "-q", "--ff-only", pin_2)
        self._mark([(landed_1, pin_1), (landed_2, pin_2)])
        self.assertEqual(self._resolve(landed_1).commit, pin_1)
        self.assertEqual(self._resolve(landed_2).commit, pin_2)

    def test_a_cause_commit_with_no_mark_is_an_error(self):
        self._setup_marked_master()
        pin = self._baseline_commit("a moves", {"a.sca": "2\n"}, start=self.mark0)
        _git(self.project_root, "checkout", "-q", "master")
        self._project_commit("e: lands with no mark", pin=pin)
        with self.assertRaisesRegex(RuntimeError, "no mark names it"):
            self._resolve("master")

    def test_a_pin_that_is_not_a_full_hash_is_an_error(self):
        self._setup_marked_master()
        self._start_series("topic/f")
        self._project_commit("f: a short pin", pin=self.first[:10])
        with self.assertRaisesRegex(RuntimeError, "not a full commit hash"):
            self._resolve("topic/f")

    def test_a_ref_and_a_trailer_in_one_entry_is_an_error(self):
        simulation_project = SimulationProject(name="demo", root_folder=self.project_root, test_parameters={"statistical": {"baseline": {**self._get_baseline_entry(), "ref": self.first}}})
        with self.assertRaises(ValueError):
            checkout_test_baseline("statistical", simulation_project=simulation_project)

    def test_the_checkout_and_the_check_of_the_trailer_form(self):
        self._land_first_series_by_fast_forward()
        _git(self.project_root, "checkout", "-q", "topic/b")
        simulation_project = self._make_project()
        self.assertEqual(checkout_test_baseline("statistical", simulation_project=simulation_project, target="master"), self.pin_b)
        with self.assertNoLogs(baseline_module._logger, level=logging.WARNING):
            check_test_baseline("statistical", simulation_project=simulation_project)
        _git(self.project_root, "checkout", "-q", "master")
        with self.assertLogs(baseline_module._logger, level=logging.WARNING) as logs:
            self.assertEqual(check_test_baseline("statistical", simulation_project=simulation_project), self.pin_b)
        self.assertIn(self.pin_a, logs.output[0])
        self.assertEqual(checkout_test_baseline("statistical", simulation_project=simulation_project), self.pin_a)
        # the baseline of another commit, for a tree that has the changes of that commit
        self.assertEqual(checkout_test_baseline("statistical", simulation_project=simulation_project, project_commit="topic/b"), self.pin_b)

if __name__ == "__main__":
    unittest.main()
