#!/usr/bin/env python3
"""
Tests the diff reader of the change-based test selection, and the change syntax on a git repository.
"""

import os
import subprocess
import tempfile
import unittest

from opp_repl.test.test_map.changes import *

def git(folder, *args):
    return subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True, check=True).stdout.strip()

def make_repository(folder, files):
    git(folder, "init", "-q")
    git(folder, "config", "user.email", "test@example.com")
    git(folder, "config", "user.name", "test")
    write_files(folder, files)
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "first")
    return git(folder, "rev-parse", "HEAD")

def write_files(folder, files):
    for path, text in files.items():
        full_path = os.path.join(folder, path)
        if text is None:
            os.remove(full_path)
            continue
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(text)

class DiffTestCase(unittest.TestCase):
    def test_parse_diff(self):
        text = "\n".join(["diff --git a/x.cc b/x.cc", "index 1..2 100644", "--- a/x.cc", "+++ b/x.cc", "@@ -3,2 +3 @@",
                          "--- a/looks like a header", "-b", "+c",
                          "diff --git a/new file.txt b/new file.txt", "new file mode 100644", "--- /dev/null", "+++ b/new file.txt", "@@ -0,0 +1 @@", "+x",
                          "diff --git a/img.png b/img.png", "deleted file mode 100644", "Binary files a/img.png and /dev/null differ", ""])
        changes = parse_diff(text, None, None)
        self.assertEqual([(change.path, change.status, change.hunks) for change in changes],
                         [("x.cc", "modified", [(3, 2, 3, 1)]), ("new file.txt", "added", [(0, 0, 1, 1)]), ("img.png", "removed", None)])

    def test_changes_of_a_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            first = make_repository(folder, {"a.txt": "1\n2\n3\n", "b.txt": "b\n"})
            write_files(folder, {"a.txt": "1\nx\n3\n", "b.txt": None})
            git(folder, "commit", "-q", "-am", "second")
            second = git(folder, "rev-parse", "HEAD")
            write_files(folder, {"c.txt": "new\n"})
            self.assertEqual(Changes(folder, second).base, first)
            self.assertEqual(Changes(folder, "HEAD~1..HEAD").target, second)
            self.assertEqual(Changes(folder, "HEAD...worktree").target, WORKTREE)
            changes = {change.path: change for change in get_file_changes(folder, first, WORKTREE)}
            self.assertEqual({path: change.status for path, change in changes.items()}, {"a.txt": "modified", "b.txt": "removed", "c.txt": "added"})
            self.assertEqual(changes["a.txt"].hunks, [(2, 1, 2, 1)])
            self.assertEqual((changes["a.txt"].get_old_text(), changes["a.txt"].get_new_text()), ("1\n2\n3\n", "1\nx\n3\n"))
            with open(os.path.join(folder, "x.patch"), "w") as f:
                f.write(git(folder, "diff", "HEAD~1", "HEAD") + "\n")
            git(folder, "checkout", "-q", "HEAD~1")
            patch = Changes(folder, os.path.join(folder, "x.patch"))
            self.assertEqual(patch.base, first)
            self.assertEqual(Side(folder, patch.target).read("a.txt"), "1\nx\n3\n")
            self.assertEqual(git(folder, "status", "--porcelain", "--untracked-files=no"), "")

if __name__ == "__main__":
    unittest.main()
