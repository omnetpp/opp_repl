#!/usr/bin/env python3
"""
Tests the git worktrees that opp_repl makes for a commit: their name and their reuse.

The tests make a small git repository in a temporary folder. They build and run no simulation.
"""

import logging
import os
import subprocess
import tempfile
import unittest

import opp_repl.simulation.project as project_module
from opp_repl.simulation.project import SimulationProject, _make_git_worktree, make_worktree_simulation_project

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
        self.git_root = os.path.join(os.path.realpath(self.folder.name), "demo")
        os.makedirs(self.git_root)
        _git(self.git_root, "init", "-q", "-b", "main", ".")
        self._commit("first", **{".gitignore": "out/\n", "a.txt": "a\n"})
        self.first_commit = _git(self.git_root, "rev-parse", "HEAD")
        _git(self.git_root, "branch", "topic/some")
        self._commit("second", **{"a.txt": "b\n"})
        self.second_commit = _git(self.git_root, "rev-parse", "HEAD")

    def _commit(self, message, folder=None, **files):
        folder = folder or self.git_root
        for name, content in files.items():
            with open(os.path.join(folder, name), "w") as f:
                f.write(content)
        _git(folder, "add", "-A")
        _git(folder, "commit", "-q", "-m", message)

    def _get_worktree_path(self, commit):
        return self.git_root + "-" + commit[:10]

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

    def test_a_folder_at_another_commit_is_an_error(self):
        _git(self.git_root, "worktree", "add", "-q", "--detach", self._get_worktree_path(self.first_commit), self.second_commit)
        with self.assertRaisesRegex(RuntimeError, "its HEAD is the commit " + self.second_commit[:10]):
            _make_git_worktree(self.git_root, "topic/some")

    def test_a_folder_that_is_not_a_worktree_is_an_error(self):
        os.makedirs(self._get_worktree_path(self.first_commit))
        with self.assertRaisesRegex(RuntimeError, "it is not a git worktree"):
            _make_git_worktree(self.git_root, "topic/some")

    def _make_simulation_project(self):
        return SimulationProject(name="demo", root_folder=self.git_root)

    def test_the_project_of_a_worktree_has_the_commit_as_its_version(self):
        simulation_project = self._make_simulation_project()
        project = make_worktree_simulation_project(simulation_project, "topic/some")
        self.addCleanup(simulation_project.get_workspace().get_simulation_projects().pop, (project.name, project.version), None)
        self.assertEqual(project.version, self.first_commit)
        self.assertEqual(project.get_root_path(), self._get_worktree_path(self.first_commit))
        self.assertIs(make_worktree_simulation_project(simulation_project, self.first_commit), project)

if __name__ == "__main__":
    unittest.main()
