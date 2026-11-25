"""
The changes of the change-based test selection (see the test selection plan of opp_repl,
``plan/pending/test-selection.md``, sections 4.2 and 9).

A change goes from the base B to the target C. C can be a commit, the working tree, or B with a patch
file. The map describes the map commit A, so the selection reads diff(A,B) and diff(A,C): each diff is
a list of :py:class:`FileChange` objects with hunks and the text of the file at both sides.
"""

import logging
import os
import re
import subprocess
import tempfile

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

WORKTREE = "worktree"

def _git(folder, *args, env=None, check=True, text=True, input=None):
    result = subprocess.run(["git", "-C", folder, *args], capture_output=True, text=text, env=env, input=input)
    if check and result.returncode != 0:
        raise Exception(f"git {' '.join(args)} failed in {folder}: {(result.stderr or '').strip()}")
    return result

def resolve_commit(root_folder, rev):
    """Returns the full commit id of *rev*, or raises an exception."""
    result = _git(root_folder, "rev-parse", "--verify", "--quiet", rev + "^{commit}", check=False)
    if result.returncode != 0:
        raise Exception(f"{rev} is not a commit of the repository of {root_folder}")
    return result.stdout.strip()

def is_commit(root_folder, rev):
    return _git(root_folder, "rev-parse", "--verify", "--quiet", rev + "^{commit}", check=False).returncode == 0

class Side:
    """One side of a diff: a commit or tree of git, or the working tree."""
    def __init__(self, root_folder, rev, description=None):
        self.root_folder = root_folder
        self.rev = rev
        self.description = description or (rev[:10] if rev != WORKTREE else "the working tree")

    def is_worktree(self):
        return self.rev == WORKTREE

    def read(self, path):
        """Returns the text of *path* (relative to the project root) at this side, or None if it does not exist."""
        if self.is_worktree():
            full_path = os.path.join(self.root_folder, path)
            if os.path.islink(full_path):
                return os.readlink(full_path)
            if not os.path.isfile(full_path):
                return None
            with open(full_path, "rb") as f:
                return f.read().decode("utf-8", errors="surrogateescape")
        result = _git(self.root_folder, "show", f"{self.rev}:./{path}", text=False, check=False)
        return result.stdout.decode("utf-8", errors="surrogateescape") if result.returncode == 0 else None

    def grep(self, regex, paths):
        """Returns the files below *paths* (relative to the project root) whose text matches the extended regular expression *regex*."""
        args = ["grep", "-l", "-I", "-E", "-e", regex]
        if self.is_worktree():
            args += ["--untracked"]
        else:
            args += [self.rev]
        result = _git(self.root_folder, *args, "--", *paths, check=False)
        if result.returncode not in (0, 1):
            raise Exception(f"git grep failed in {self.root_folder}: {result.stderr.strip()}")
        files = []
        for line in result.stdout.splitlines():
            # a commit prefixes each file with "<rev>:"
            files.append(line[len(self.rev) + 1:] if not self.is_worktree() and line.startswith(self.rev + ":") else line)
        return files

class FileChange:
    """
    A changed file of one diff. *path* is relative to the project root, *status* is ``added``,
    ``removed`` or ``modified``, and *hunks* is a list of ``(old start, old count, new start, new
    count)`` as in ``git diff -U0``, or None for a binary file. For a pure insertion, the old start is
    the line after which the new lines come.
    """
    def __init__(self, path, status, hunks, old_side, new_side):
        self.path = path
        self.status = status
        self.hunks = hunks
        self.old_side = old_side
        self.new_side = new_side
        self._texts = {}

    def __repr__(self):
        return f"FileChange({self.path!r}, {self.status}, {len(self.hunks) if self.hunks is not None else 'binary'} hunks)"

    def get_old_text(self):
        if "old" not in self._texts:
            self._texts["old"] = None if self.status == "added" else self.old_side.read(self.path)
        return self._texts["old"]

    def get_new_text(self):
        if "new" not in self._texts:
            self._texts["new"] = None if self.status == "removed" else self.new_side.read(self.path)
        return self._texts["new"]

def _unquote_git_path(path):
    # git writes a path with special characters as a C string in quotes
    if not path.startswith('"'):
        return path
    body = path[1:-1]
    result = bytearray()
    index = 0
    escapes = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body):
            following = body[index + 1]
            if following in escapes:
                result.append(escapes[following])
                index += 2
                continue
            if following.isdigit():
                result.append(int(body[index + 1:index + 4], 8))
                index += 4
                continue
        result.extend(char.encode("utf-8"))
        index += 1
    return result.decode("utf-8", errors="surrogateescape")

def _strip_prefix(path, prefix):
    path = _unquote_git_path(path)
    return path[len(prefix):] if path.startswith(prefix) else path

_HUNK_REGEX = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

def parse_diff(text, old_side, new_side):
    """Returns the :py:class:`FileChange` objects of the output of ``git diff -U0 --no-renames --src-prefix=a/ --dst-prefix=b/``."""
    changes = []
    lines = text.split("\n")
    index = 0
    current = None
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.startswith("diff --git "):
            rest = line[len("diff --git "):]
            if rest.startswith('"'):
                end = rest.index('"', 1)
                while rest[end - 1] == "\\":
                    end = rest.index('"', end + 1)
                path = _strip_prefix(rest[:end + 1], "a/")
            else:
                # without renames both paths are the same: "a/<path> b/<path>"
                path = rest[2:2 + (len(rest) - 5) // 2]
            current = FileChange(path, "modified", [], old_side, new_side)
            changes.append(current)
        elif current is None:
            continue
        elif line.startswith("new file mode"):
            current.status = "added"
        elif line.startswith("deleted file mode"):
            current.status = "removed"
        elif line.startswith("Binary files "):
            current.hunks = None
        elif line.startswith("--- "):
            if line != "--- /dev/null":
                current.path = _strip_prefix(line[4:], "a/")
        elif line.startswith("+++ "):
            if line != "+++ /dev/null":
                current.path = _strip_prefix(line[4:], "b/")
        elif line.startswith("@@ "):
            match = _HUNK_REGEX.match(line)
            if not match:
                raise Exception(f"Cannot parse the hunk header {line!r} of {current.path}")
            old_start, old_count, new_start, new_count = int(match.group(1)), int(match.group(2) or 1), int(match.group(3)), int(match.group(4) or 1)
            current.hunks.append((old_start, old_count, new_start, new_count))
            # skip the lines of the hunk; a line of the file can look like a header line
            remaining_old, remaining_new = old_count, new_count
            while (remaining_old > 0 or remaining_new > 0) and index < len(lines):
                hunk_line = lines[index]
                index += 1
                if hunk_line.startswith("-"):
                    remaining_old -= 1
                elif hunk_line.startswith("+"):
                    remaining_new -= 1
                elif hunk_line.startswith(" "):
                    remaining_old -= 1
                    remaining_new -= 1
            while index < len(lines) and lines[index].startswith("\\"):
                index += 1
    return changes

_DIFF_ARGS = ["-c", "core.quotePath=false", "diff", "--no-renames", "--no-ext-diff", "--no-textconv", "--no-color", "-U0", "--relative", "--src-prefix=a/", "--dst-prefix=b/"]

def get_file_changes(root_folder, old_rev, new_rev):
    """
    Returns the :py:class:`FileChange` objects of the diff from the commit *old_rev* to *new_rev* (a
    commit, a tree, or :py:data:`WORKTREE`), for the files below *root_folder*. A rename is a removal
    and an addition. For the working tree, the untracked files that git does not ignore are added
    files.
    """
    old_side = Side(root_folder, old_rev)
    new_side = Side(root_folder, new_rev)
    if new_rev == WORKTREE:
        diff = _git(root_folder, *_DIFF_ARGS, old_rev, "--", text=False).stdout.decode("utf-8", errors="surrogateescape")
        changes = parse_diff(diff, old_side, new_side)
        untracked = _git(root_folder, "ls-files", "--others", "--exclude-standard", "-z", text=False).stdout.decode("utf-8", errors="surrogateescape")
        for path in untracked.split("\0"):
            if path:
                changes.append(FileChange(path, "added", [], old_side, new_side))
    else:
        diff = _git(root_folder, *_DIFF_ARGS, old_rev, new_rev, "--", text=False).stdout.decode("utf-8", errors="surrogateescape")
        changes = parse_diff(diff, old_side, new_side)
    return changes

def _make_patch_tree(root_folder, base_commit, patch_file):
    # apply the patch to the base in a temporary index; the user's index and working tree do not change
    top_folder = _git(root_folder, "rev-parse", "--show-toplevel").stdout.strip()
    with tempfile.TemporaryDirectory() as folder:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(folder, "index"))
        _git(top_folder, "read-tree", base_commit, env=env)
        _git(top_folder, "apply", "--cached", os.path.abspath(patch_file), env=env)
        return _git(top_folder, "write-tree", env=env).stdout.strip()

class Changes:
    """
    A change from the base B to the target C. *changes* is one of:

    - ``worktree``: B is ``HEAD``, C is the working tree with the untracked files;
    - ``<rev>``: B is the first parent of the commit, C is the commit;
    - ``<rev1>..<rev2>``: B is *rev1*, C is *rev2*; an empty side is ``HEAD``;
    - ``<rev1>...<rev2>``: B is the merge base of the two, C is *rev2*;
    - the path of a patch file: B is ``HEAD``, C is B with the patch.

    *rev2* can be ``worktree``.
    """
    def __init__(self, root_folder, changes=WORKTREE):
        self.root_folder = root_folder
        self.changes = changes
        def target(rev):
            return WORKTREE if rev == WORKTREE else resolve_commit(root_folder, rev or "HEAD")
        if changes == WORKTREE:
            self.base = resolve_commit(root_folder, "HEAD")
            self.target = WORKTREE
        elif os.path.isfile(changes) and not is_commit(root_folder, changes):
            self.base = resolve_commit(root_folder, "HEAD")
            self.target = _make_patch_tree(root_folder, self.base, changes)
        elif "..." in changes:
            left, right = changes.split("...", 1)
            self.target = target(right)
            other = resolve_commit(root_folder, "HEAD") if self.target == WORKTREE else self.target
            self.base = _git(root_folder, "merge-base", resolve_commit(root_folder, left or "HEAD"), other).stdout.strip()
        elif ".." in changes:
            left, right = changes.split("..", 1)
            self.base = resolve_commit(root_folder, left or "HEAD")
            self.target = target(right)
        else:
            self.target = resolve_commit(root_folder, changes)
            parents = _git(root_folder, "rev-list", "--parents", "-n", "1", self.target).stdout.split()
            # a root commit has no parent: its base is the empty tree
            self.base = parents[1] if len(parents) > 1 else _git(root_folder, "hash-object", "-t", "tree", "/dev/null").stdout.strip()

    def describe(self):
        target = "the working tree" if self.target == WORKTREE else self.target[:10]
        return f"{self.changes} (B = {self.base[:10]}, C = {target})"

    def is_target_dirty(self):
        """True if the target is a commit and the working tree has changes of tracked files, which the change does not include."""
        return self.target != WORKTREE and bool(_git(self.root_folder, "status", "--porcelain", "--untracked-files=no", "--", ".").stdout.strip())
