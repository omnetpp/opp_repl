#!/usr/bin/env python3
"""
Tests the git worktrees that opp_repl makes for a commit: their name, their reuse, and the proof
that nobody uses a worktree, without which opp_repl does not remove it.

The tests make a small git repository in a temporary folder. They build and run no simulation.
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import opp_repl.simulation.project as project_module
from opp_repl.simulation.project import (SimulationProject, _make_git_worktree, _remove_git_worktree, _remove_unused_git_worktrees, _unlock_worktree,
                                         get_unused_worktree_max_age_days, make_worktree_simulation_project, remove_unused_worktrees, remove_worktree_simulation_project)

def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

class WorktreeTestCase(unittest.TestCase):
    def setUp(self):
        # the test output has no use for the lines on each worktree and each git command
        for logger in [project_module._logger, logging.getLogger("git")]:
            self.addCleanup(logger.setLevel, logger.level)
            logger.setLevel(logging.WARNING)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self._release_locks)
        self.git_root = os.path.join(os.path.realpath(self.folder.name), "demo")
        os.makedirs(self.git_root)
        _git(self.git_root, "init", "-q", "-b", "main", ".")
        self._commit("first", **{".gitignore": "out/\n", "a.txt": "a\n"})
        self.first_commit = _git(self.git_root, "rev-parse", "HEAD")
        _git(self.git_root, "branch", "topic/some")
        self._commit("second", **{"a.txt": "b\n"})
        self.second_commit = _git(self.git_root, "rev-parse", "HEAD")

    def _release_locks(self):
        for worktree_path in list(project_module._worktree_locks):
            _unlock_worktree(worktree_path)

    def _commit(self, message, folder=None, **files):
        folder = folder or self.git_root
        for name, content in files.items():
            with open(os.path.join(folder, name), "w") as f:
                f.write(content)
        _git(folder, "add", "-A")
        _git(folder, "commit", "-q", "-m", message)

    def _get_worktree_path(self, commit):
        return self.git_root + "-" + commit[:10]

    def _make_unused_worktree(self, git_hash="topic/some"):
        """Makes a worktree, then releases the lock as the end of the process does."""
        worktree_path = _make_git_worktree(self.git_root, git_hash)
        _unlock_worktree(worktree_path)
        return worktree_path

    def _get_marker_path(self, worktree_path):
        return os.path.join(_git(worktree_path, "rev-parse", "--absolute-git-dir"), "opp_repl")

    def _set_last_use(self, worktree_path, days_ago):
        last_use = time.time() - days_ago * 86400
        os.utime(self._get_marker_path(worktree_path), (last_use, last_use))

    # the name and the reuse

    def test_the_name_is_the_short_hash_of_the_commit(self):
        worktree_path = _make_git_worktree(self.git_root, "topic/some")
        self.assertEqual(worktree_path, self._get_worktree_path(self.first_commit))
        self.assertEqual(_git(worktree_path, "rev-parse", "HEAD"), self.first_commit)
        self.assertEqual(subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=worktree_path, capture_output=True).returncode, 1)

    def test_a_ref_and_a_hash_of_one_commit_give_one_worktree(self):
        self.assertEqual(_make_git_worktree(self.git_root, "topic/some"), _make_git_worktree(self.git_root, self.first_commit))
        self.assertEqual(_make_git_worktree(self.git_root, "topic/some"), _make_git_worktree(self.git_root, self.first_commit[:12]))

    def test_a_ref_that_moved_gives_another_worktree(self):
        old_worktree_path = _make_git_worktree(self.git_root, "main")
        self._commit("third", **{"a.txt": "c\n"})
        new_worktree_path = _make_git_worktree(self.git_root, "main")
        self.assertNotEqual(old_worktree_path, new_worktree_path)
        self.assertEqual(_git(old_worktree_path, "rev-parse", "HEAD"), self.second_commit)
        self.assertEqual(_git(new_worktree_path, "rev-parse", "HEAD"), _git(self.git_root, "rev-parse", "main"))

    def test_an_unknown_ref_is_an_error(self):
        with self.assertRaisesRegex(RuntimeError, "Cannot find the git commit"):
            _make_git_worktree(self.git_root, "no-such-ref")

    def test_the_marker_records_the_commit_and_the_ref(self):
        worktree_path = _make_git_worktree(self.git_root, "topic/some")
        with open(self._get_marker_path(worktree_path)) as f:
            self.assertEqual(json.load(f), {"commit": self.first_commit, "ref": "topic/some"})
        self.assertEqual(_git(worktree_path, "status", "--porcelain"), "")

    def test_a_folder_without_the_marker_at_the_commit_is_used_and_never_removed(self):
        worktree_path = self._get_worktree_path(self.first_commit)
        _git(self.git_root, "worktree", "add", "-q", "--detach", worktree_path, self.first_commit)
        self.assertEqual(_make_git_worktree(self.git_root, "topic/some"), worktree_path)
        self.assertFalse(os.path.exists(self._get_marker_path(worktree_path)))
        self.assertEqual(_remove_git_worktree(worktree_path), "opp_repl did not make it")
        self.assertTrue(os.path.isdir(worktree_path))

    def test_a_folder_at_another_commit_is_an_error(self):
        _git(self.git_root, "worktree", "add", "-q", "--detach", self._get_worktree_path(self.first_commit), self.second_commit)
        with self.assertRaisesRegex(RuntimeError, "its HEAD is the commit " + self.second_commit[:10]):
            _make_git_worktree(self.git_root, "topic/some")

    def test_a_folder_that_is_not_a_worktree_is_an_error(self):
        os.makedirs(self._get_worktree_path(self.first_commit))
        with self.assertRaisesRegex(RuntimeError, "it is not a git worktree"):
            _make_git_worktree(self.git_root, "topic/some")

    # the proof that nobody uses a worktree

    def test_an_unused_worktree_is_removed(self):
        worktree_path = self._make_unused_worktree()
        self.assertIsNone(_remove_git_worktree(worktree_path))
        self.assertFalse(os.path.exists(worktree_path))
        self.assertNotIn(worktree_path, _git(self.git_root, "worktree", "list"))

    def test_ignored_files_do_not_count(self):
        worktree_path = self._make_unused_worktree()
        os.makedirs(os.path.join(worktree_path, "out"))
        with open(os.path.join(worktree_path, "out", "lib.so"), "w") as f:
            f.write("build output\n")
        self.assertIsNone(_remove_git_worktree(worktree_path))
        self.assertFalse(os.path.exists(worktree_path))

    def test_check_2_this_process_uses_it(self):
        worktree_path = _make_git_worktree(self.git_root, "topic/some")
        self.assertEqual(_remove_git_worktree(worktree_path), "this process uses it")
        self.assertTrue(os.path.isdir(worktree_path))

    def test_check_2_another_process_uses_it(self):
        worktree_path = self._make_unused_worktree()
        code = "import fcntl, sys, time; f = open(sys.argv[1]); fcntl.flock(f, fcntl.LOCK_SH); print('locked', flush=True); time.sleep(60)"
        process = subprocess.Popen([sys.executable, "-c", code, self._get_marker_path(worktree_path)], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            self.assertEqual(_remove_git_worktree(worktree_path), "another opp_repl process uses it")
        finally:
            process.kill()
            process.wait()
            process.stdout.close()
        self.assertIsNone(_remove_git_worktree(worktree_path))

    def test_check_3_a_changed_file(self):
        worktree_path = self._make_unused_worktree()
        with open(os.path.join(worktree_path, "a.txt"), "w") as f:
            f.write("changed\n")
        self.assertEqual(_remove_git_worktree(worktree_path), "it has changed or new files")
        self.assertTrue(os.path.isdir(worktree_path))

    def test_check_3_a_new_file(self):
        worktree_path = self._make_unused_worktree()
        with open(os.path.join(worktree_path, "new.txt"), "w") as f:
            f.write("new\n")
        self.assertEqual(_remove_git_worktree(worktree_path), "it has changed or new files")
        self.assertTrue(os.path.isdir(worktree_path))

    def test_check_3_a_new_commit(self):
        # git removes such a worktree without --force, thus opp_repl must do this check
        worktree_path = self._make_unused_worktree()
        self._commit("in the worktree", folder=worktree_path, **{"a.txt": "work\n"})
        self.assertEqual(_remove_git_worktree(worktree_path), "its HEAD is not the detached commit that opp_repl checked out")
        self.assertTrue(os.path.isdir(worktree_path))

    def test_check_3_a_branch(self):
        worktree_path = self._make_unused_worktree()
        _git(worktree_path, "checkout", "-q", "-b", "work")
        self.assertEqual(_remove_git_worktree(worktree_path), "its HEAD is not the detached commit that opp_repl checked out")
        self.assertTrue(os.path.isdir(worktree_path))

    def test_check_4_a_process_in_it(self):
        worktree_path = self._make_unused_worktree()
        process = subprocess.Popen(["sleep", "60"], cwd=worktree_path)
        try:
            self.assertEqual(_remove_git_worktree(worktree_path), f"process {process.pid} (sleep) has its working directory or a file in it")
        finally:
            process.kill()
            process.wait()
        self.assertIsNone(_remove_git_worktree(worktree_path))

    # the time of the removal

    def test_a_worktree_stays_until_its_last_use_is_old(self):
        worktree_path = self._make_unused_worktree()
        self.assertRegex(_remove_git_worktree(worktree_path, max_age_days=14), "its last use was 0.0 days ago")
        self._set_last_use(worktree_path, days_ago=15)
        self.assertIsNone(_remove_git_worktree(worktree_path, max_age_days=14))

    def test_a_use_sets_the_time_again(self):
        worktree_path = self._make_unused_worktree()
        self._set_last_use(worktree_path, days_ago=15)
        self.assertEqual(self._make_unused_worktree(), worktree_path)
        self.assertRegex(_remove_git_worktree(worktree_path, max_age_days=14), "its last use was 0.0 days ago")

    def test_a_new_worktree_removes_the_old_unused_worktrees(self):
        old_worktree_path = self._make_unused_worktree("topic/some")
        self._set_last_use(old_worktree_path, days_ago=15)
        _make_git_worktree(self.git_root, "main")
        self.assertFalse(os.path.exists(old_worktree_path))

    def test_the_setting_none_turns_the_automatic_removal_off(self):
        old_worktree_path = self._make_unused_worktree("topic/some")
        self._set_last_use(old_worktree_path, days_ago=15)
        with mock.patch.dict(os.environ, {"OPP_WORKTREE_MAX_AGE_DAYS": "none"}):
            self.assertIsNone(get_unused_worktree_max_age_days())
            _make_git_worktree(self.git_root, "main")
        self.assertTrue(os.path.isdir(old_worktree_path))

    def test_the_setting_gives_the_number_of_days(self):
        with mock.patch.dict(os.environ, {"OPP_WORKTREE_MAX_AGE_DAYS": "30"}):
            self.assertEqual(get_unused_worktree_max_age_days(), 30)
        with mock.patch.dict(os.environ):
            os.environ.pop("OPP_WORKTREE_MAX_AGE_DAYS", None)
            self.assertEqual(get_unused_worktree_max_age_days(), 14)

    def test_only_the_worktrees_of_opp_repl_are_examined(self):
        worktree_path = self._make_unused_worktree("topic/some")
        user_worktree_path = self.git_root + "-main"
        _git(self.git_root, "worktree", "add", "-q", "--detach", user_worktree_path, "main")
        self.assertEqual(_remove_unused_git_worktrees(self.git_root, 0), {worktree_path: None})
        self.assertFalse(os.path.exists(worktree_path))
        self.assertTrue(os.path.isdir(user_worktree_path))

    # the simulation project of a worktree

    def _make_simulation_project(self):
        return SimulationProject(name="demo", root_folder=self.git_root)

    def test_the_project_of_a_worktree_has_the_commit_as_its_version(self):
        simulation_project = self._make_simulation_project()
        project = make_worktree_simulation_project(simulation_project, "topic/some")
        self.addCleanup(remove_worktree_simulation_project, project)
        self.assertEqual(project.version, self.first_commit)
        self.assertEqual(project.get_root_path(), self._get_worktree_path(self.first_commit))
        self.assertIs(make_worktree_simulation_project(simulation_project, self.first_commit), project)

    def test_the_removal_of_a_project_removes_an_unused_worktree(self):
        project = make_worktree_simulation_project(self._make_simulation_project(), "topic/some")
        remove_worktree_simulation_project(project)
        self.assertFalse(os.path.exists(self._get_worktree_path(self.first_commit)))

    def test_the_removal_of_a_project_keeps_a_worktree_with_work_in_it(self):
        simulation_project = self._make_simulation_project()
        project = make_worktree_simulation_project(simulation_project, "topic/some")
        worktree_path = self._get_worktree_path(self.first_commit)
        with open(os.path.join(worktree_path, "new.txt"), "w") as f:
            f.write("new\n")
        with self.assertLogs(project_module._logger, logging.WARNING) as logs:
            remove_worktree_simulation_project(project)
        self.assertIn("stays: it has changed or new files", logs.output[0])
        self.assertTrue(os.path.isdir(worktree_path))
        self.assertEqual(remove_unused_worktrees(simulation_project), {worktree_path: "it has changed or new files"})

if __name__ == "__main__":
    unittest.main()
