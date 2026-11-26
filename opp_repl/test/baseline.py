"""
This module checks out the baseline repositories of the tests of a simulation project.

A test kind can compare its results with stored results that are in another git repository. The
``baseline`` entry of the kind in the ``test_parameters`` of the ``.opp`` file declares that
repository: ``repository`` is its URL or its ``owner/name`` on GitHub, and ``folder`` is the folder of
the clone below the project root. The entry names the commit to use in one of two forms:

- ``ref`` is the commit itself. With a full commit hash as ``ref``, each commit of the simulation
  project names the exact stored results that it passes with.
- ``trailer`` is the key of a git trailer, for example ``Statistical-Baseline``. A commit of the
  project that changes the stored results has this trailer with the full hash of a baseline commit:
  the pin. After the project commit lands on its target branch, a landing job puts the baseline
  commits onto the default branch of the baseline repository and adds a mark: a commit with no change
  of files whose message has a trailer ``Baseline-Of: <project hash> <baseline hash>`` for each landed
  pin. :py:func:`resolve_test_baseline` finds the baseline of a project commit from the two histories.

The main function is :py:func:`checkout_test_baselines`. A test never changes a baseline checkout:
:py:func:`check_test_baseline` only reports a checkout that is not at the declared commit.
"""

import logging
import os
import re
import subprocess

_logger = logging.getLogger(__name__)

_full_hash_pattern = re.compile(r"^[0-9a-f]{40}$")

MARK_TRAILER = "Baseline-Of"
"""The trailer key of a mark in a baseline repository: ``Baseline-Of: <project hash> <baseline hash>``."""

_default_branch_names = ("refs/remotes/origin/HEAD", "origin/master", "origin/main", "master", "main")

def _git(folder, *args, env=None, input=None):
    """Runs a git command in the folder and returns its output. An error of git raises an exception with the message of git."""
    result = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True, env=env, input=input)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {folder}:\n{result.stderr.strip()}")
    return result.stdout.strip()

def _find_commit(folder, name):
    """Returns the full hash of the commit that the name gives in the repository of the folder, or None."""
    result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", name + "^{commit}"], cwd=folder, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None

def _is_ancestor(folder, ancestor, commit):
    return subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, commit], cwd=folder, capture_output=True).returncode == 0

def _is_git_checkout(folder):
    # a folder below the project root with no .git entry of its own is a part of the project repository
    return os.path.exists(os.path.join(folder, ".git"))

def _get_simulation_project(simulation_project):
    if simulation_project is None:
        from opp_repl.simulation.workspace import get_default_simulation_project  # lazy: avoid the test/* import cycle
        simulation_project = get_default_simulation_project()
    return simulation_project

def _get_declared_baseline(kind, simulation_project):
    baseline = simulation_project.get_test_baseline(kind)
    if not baseline:
        raise ValueError(f"The {kind} tests of the project {simulation_project.get_name()} declare no baseline repository")
    if baseline.get("ref") and baseline.get("trailer"):
        raise ValueError(f"The {kind} baseline entry of the project {simulation_project.get_name()} has a ref and a trailer, it can have only one of them")
    return baseline

def get_test_baseline_url(repository):
    """Returns the URL of a baseline repository: an ``owner/name`` value is a repository on GitHub, any other value is a URL."""
    return repository if ("://" in repository or repository.startswith("git@")) else f"https://github.com/{repository}.git"

def get_test_baseline_kinds(simulation_project=None):
    """Returns the test kinds of the simulation project that declare a baseline repository."""
    simulation_project = _get_simulation_project(simulation_project)
    return [kind for kind, parameters in simulation_project.test_parameters.items() if parameters.get("baseline")]

def get_test_baseline_commit(kind, simulation_project=None, baseline_simulation_project=None):
    """
    Returns the full hash of the commit that the baseline checkout of the test kind is at, or None when
    the kind declares no baseline repository or the folder is not a git checkout.

    Parameters:
        kind (str):
            The test kind, for example ``"statistical"`` or ``"chart"``.

        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>`):
            The project that declares the baseline. If unspecified, then the default simulation project is used.

        baseline_simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>`):
            The project whose root folder holds the checkout. If unspecified, then the simulation project is used.
    """
    simulation_project = _get_simulation_project(simulation_project)
    baseline = simulation_project.get_test_baseline(kind)
    if not baseline:
        return None
    folder = (baseline_simulation_project or simulation_project).get_full_path(baseline.get("folder") or ".")
    return _find_commit(folder, "HEAD") if _is_git_checkout(folder) else None

class TestBaseline:
    """
    The baseline of one commit of a simulation project for one test kind, as :py:func:`resolve_test_baseline` finds it.

    Attributes:
        commit (str): the full hash of the baseline commit, the commit that the tests compare against.
        project_commit (str or None): the commit of the simulation project, for the ``trailer`` form.
        ref (str or None): the ``ref`` of the entry, for the ``ref`` form.
        target (str or None): the target branch of the project, for example ``origin/master``.
        base (str or None): B, the merge base of the project commit and the target branch.
        marked (str or None): A, the newest first-parent ancestor of B that a mark names, or None.
        master (str or None): M, the baseline that the mark gives for A, or the old ``ref`` when no mark names an ancestor of B.
        cause (str or None): the newest commit after B that has the pin trailer, or None.
        pin (str or None): S, the pin of that commit.
        rebased (bool): True when the commit is the baseline branch up to S, rebased locally onto M.
    """
    __test__ = False  # not a test case of pytest

    def __init__(self, commit, project_commit=None, ref=None, target=None, base=None, marked=None, master=None, cause=None, pin=None, rebased=False):
        self.commit = commit
        self.project_commit = project_commit
        self.ref = ref
        self.target = target
        self.base = base
        self.marked = marked
        self.master = master
        self.cause = cause
        self.pin = pin
        self.rebased = rebased

    def get_description(self):
        """Returns the lines that tell how the baseline follows from the two histories."""
        if self.ref is not None:
            return [f"the ref {self.ref} of the entry"]
        lines = [f"B {self.base}: the merge base of {self.project_commit} and {self.target}"]
        if self.marked:
            lines.append(f"M {self.master}: the baseline that a mark gives for {self.marked}")
        else:
            lines.append(f"M {self.master}: the newest ref before B, no mark names an ancestor of B")
        if self.pin is None:
            lines.append("no pin after B: the baseline is M")
        elif self.rebased:
            lines.append(f"S {self.pin}: the pin of {self.cause}, rebased onto M as {self.commit}")
        else:
            lines.append(f"S {self.pin}: the pin of {self.cause}, which needs no rebase")
        return lines

def _get_project_repository(simulation_project):
    root = simulation_project.get_full_path(".")
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"The project {simulation_project.get_name()} in {root} is not in a git repository, and a baseline entry with a trailer needs the history of the project")
    return result.stdout.strip()

def _find_default_branch(folder, name=None):
    """Returns the name and the commit of the branch to use: the name when it is given, else the first of the usual names of a default branch that the repository has."""
    for candidate in [name] if name else _default_branch_names:
        commit = _find_commit(folder, candidate)
        if commit:
            return candidate, commit
    if name:
        raise RuntimeError(f"The branch {name} is not in the repository {folder}")
    raise RuntimeError(f"The repository {folder} has none of the branches {', '.join(_default_branch_names)}, name the target branch")

def _read_pin_values(values, commit, trailer):
    values = [value.strip() for value in values.split("\x1d") if value.strip()]
    if len(values) > 1:
        raise RuntimeError(f"The commit {commit} has {len(values)} trailers {trailer}, it can have only one")
    if values and not _full_hash_pattern.match(values[0]):
        raise RuntimeError(f"The trailer {trailer} of the commit {commit} is {values[0]}, which is not a full commit hash")
    return values[0] if values else None

def read_marks(folder, branch):
    """Returns the baseline hash of each project commit that a mark on the branch of the baseline repository names. A newer mark wins."""
    output = _git(folder, "log", f"--format=%(trailers:key={MARK_TRAILER},valueonly,separator=%x1d)%x1e", f"--grep=^{MARK_TRAILER}: ", branch)
    marks = {}
    for record in output.split("\x1e"):
        for value in record.split("\x1d"):
            parts = value.split()
            if len(parts) == 2 and all(_full_hash_pattern.match(part) for part in parts):
                marks.setdefault(parts[0], parts[1])
    return marks

def _find_marked_ancestor(repository, start, trailer, marks):
    """
    Returns the newest first-parent ancestor of the start commit, the start commit included, that a mark
    names, or None. A commit with the pin trailer before that ancestor has no mark yet: the landing job did
    not put its baseline onto the default branch of the baseline repository, so its baseline is not known.
    """
    process = subprocess.Popen(["git", "log", "--first-parent", f"--format=%H%x1f%(trailers:key={trailer},valueonly,separator=%x1d)", start], cwd=repository, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        for line in process.stdout:
            commit, values = line.rstrip("\n").split("\x1f", 1)
            if commit in marks:
                return commit
            if _read_pin_values(values, commit, trailer):
                raise RuntimeError(f"The commit {commit} of the target branch has the trailer {trailer}, but no mark names it: the landing job did not land its baseline yet, or it failed")
        return None
    finally:
        process.kill()
        process.wait()

def _find_old_ref(simulation_project, repository, start, kind):
    """Returns the newest first-parent ancestor of the start commit whose ``.opp`` file has a full-hash ``ref`` for the kind, and that ``ref``, or None."""
    from opp_repl.simulation.workspace import _parse_opp_source  # lazy: avoid the test/* import cycle
    opp_path = os.path.relpath(os.path.join(simulation_project.get_full_path("."), simulation_project.get_name() + ".opp"), repository)
    # the file is the same in each commit until the next commit that changes it
    for commit in _git(repository, "log", "--first-parent", "--format=%H", start, "--", opp_path).splitlines():
        result = subprocess.run(["git", "show", f"{commit}:{opp_path}"], cwd=repository, capture_output=True, text=True)
        if result.returncode != 0:
            continue  # the commit removes the file
        try:
            _, kwargs = _parse_opp_source(result.stdout, f"{commit}:{opp_path}")
        except (ValueError, SyntaxError):
            continue
        ref = (kwargs.get("test_parameters") or {}).get(kind, {}).get("baseline", {}).get("ref")
        if ref and _full_hash_pattern.match(ref):
            return commit, ref
    return None

def _find_pin(repository, base, commit, trailer):
    """Returns the newest commit in ``base..commit`` that has the pin trailer, and its pin, or None."""
    output = _git(repository, "log", "--topo-order", f"--format=%H%x1f%(trailers:key={trailer},valueonly,separator=%x1d)", f"{base}..{commit}")
    for line in output.splitlines():
        cause, values = line.split("\x1f", 1)
        pin = _read_pin_values(values, cause, trailer)
        if pin:
            return cause, pin
    return None

def _ensure_commit(folder, commit, fetch):
    if _find_commit(folder, commit) is None:
        if not fetch:
            raise RuntimeError(f"The baseline repository in {folder} does not have the commit {commit}, use opp_checkout_test_baselines")
        # a commit can be on no branch, as the head of a pull request is
        _git(folder, "fetch", "--quiet", "origin", commit)
        if _find_commit(folder, commit) is None:
            raise RuntimeError(f"The baseline repository in {folder} does not give the commit {commit}")

def _read_commit_identity(folder, commit):
    fields = _git(folder, "log", "-1", "--date=raw", "--format=%an%x00%ae%x00%ad%x00%cn%x00%ce%x00%cd", commit).split("\x00")
    env = dict(os.environ)
    for key, value in zip(("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE"), fields):
        env[key] = value
    return env

def _read_commit_message(folder, commit):
    result = subprocess.run(["git", "cat-file", "commit", commit], cwd=folder, capture_output=True, text=True, check=True)
    return result.stdout.split("\n\n", 1)[1] if "\n\n" in result.stdout else ""

def rebase_baseline_branch(folder, pin, onto, branch):
    """
    Returns the baseline branch up to the pin, rebased onto the commit ``onto``, and whether a rebase was necessary.

    The baseline branch is the commits in ``base..pin``, where the base is the merge base of the pin and the
    default branch. A pin on the default branch landed by a fast-forward and is its own result, and so is a pin
    whose base has the files of ``onto``, for example a base that is the mark after ``onto``. The rebased
    commits keep the author, the committer, the dates and the message of each commit, so their hashes are the
    same on each machine. The function stops with an error if the branch has a merge commit, or if a file
    that the branch changes also differs between the base and ``onto`` (an overlap).

    Parameters:
        folder (str): the clone of the baseline repository, which has the pin, ``onto`` and the branch.
        pin (str): the last commit of the baseline branch.
        onto (str): the commit to rebase onto, M of :py:func:`resolve_test_baseline`.
        branch (str): the default branch of the baseline repository.

    Returns (tuple):
        the full hash of the result, and True when the result is a new rebased commit.
    """
    if _is_ancestor(folder, pin, branch):
        return pin, False
    base = _git(folder, "merge-base", pin, branch)
    if _git(folder, "rev-parse", base + "^{tree}") == _git(folder, "rev-parse", onto + "^{tree}"):
        # for example a branch that starts on the mark after M: the mark changes no file
        return pin, False
    commits = [line.split() for line in _git(folder, "rev-list", "--reverse", "--topo-order", "--parents", f"{base}..{pin}").splitlines()]
    merges = [parts[0] for parts in commits if len(parts) != 2]
    if merges:
        raise RuntimeError(f"The baseline branch of the pin {pin} has the merge commit {merges[0]}, a baseline branch must be linear")
    changed = set(_git(folder, "diff", "--name-only", "--no-renames", base, pin).splitlines())
    moved = set(_git(folder, "diff", "--name-only", "--no-renames", base, onto).splitlines())
    common = sorted(changed & moved)
    if common:
        raise RuntimeError(f"The baseline branch of the pin {pin} overlaps with {onto}: since the base {base}, both change {', '.join(common)}. Record these results again on {onto}")
    result = onto
    for commit, parent in commits:
        merge = subprocess.run(["git", "merge-tree", "--write-tree", "--name-only", f"--merge-base={parent}", result, commit], cwd=folder, capture_output=True, text=True)
        if merge.returncode != 0:
            raise RuntimeError(f"The rebase of the baseline commit {commit} onto {result} conflicts:\n{merge.stdout.strip() or merge.stderr.strip()}")
        tree = merge.stdout.split("\n", 1)[0].strip()
        result = _git(folder, "commit-tree", tree, "-p", result, "-F", "-", env=_read_commit_identity(folder, commit), input=_read_commit_message(folder, commit))
    return result, True

def _get_checkout_folder(kind, simulation_project, baseline_simulation_project=None):
    baseline = simulation_project.get_test_baseline(kind)
    return (baseline_simulation_project or simulation_project).get_full_path(baseline.get("folder") or ".")

def resolve_test_baseline(kind, simulation_project=None, baseline_simulation_project=None, project_commit="HEAD", target=None, fetch=True):
    """
    Finds the baseline commit of one commit of the simulation project for one test kind.

    With the ``ref`` form, the baseline is that ref. With the ``trailer`` form, the function follows these steps:

    1. B is the merge base of the project commit and the target branch of the project.
    2. A is the newest first-parent ancestor of B, B included, that a mark on the default branch of the
       baseline repository names. M is the baseline hash of that mark. If no mark names an ancestor of B,
       M is the ``ref`` of the newest ancestor of B whose ``.opp`` file has one. A commit with the trailer
       between B and A is an error: the landing job did not mark it yet.
    3. S is the pin of the newest commit in ``B..commit`` that has the trailer. With no such commit, the
       baseline is M.
    4. Else the baseline is the baseline branch up to S, rebased onto M (:py:func:`rebase_baseline_branch`).

    The clone of the baseline repository must exist. The function can add rebased commits to it, but it
    does not change its checkout.

    Parameters:
        kind (str):
            The test kind, for example ``"statistical"`` or ``"chart"``.

        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>`):
            The project that declares the baseline. If unspecified, then the default simulation project is used.

        baseline_simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>`):
            The project whose root folder holds the checkout. If unspecified, then the simulation project is used.

        project_commit (str):
            The commit of the simulation project. The default is ``HEAD``.

        target (str):
            The target branch of the project, for example ``origin/master``. If unspecified, then the first one of
            ``origin/HEAD``, ``origin/master``, ``origin/main``, ``master`` and ``main`` that the project repository has.

        fetch (bool):
            When true, the function fetches the branches of the baseline repository, to see the newest marks,
            and each commit that the clone does not have.

    Returns (:py:class:`TestBaseline`):
        the baseline and the commits that it follows from.
    """
    simulation_project = _get_simulation_project(simulation_project)
    baseline = _get_declared_baseline(kind, simulation_project)
    folder = _get_checkout_folder(kind, simulation_project, baseline_simulation_project)
    if not _is_git_checkout(folder):
        raise RuntimeError(f"The {kind} baseline repository {baseline['repository']} is not checked out in {folder}, use opp_checkout_test_baselines")
    ref = baseline.get("ref")
    if ref:
        commit = _find_commit(folder, ref) if _full_hash_pattern.match(ref) else None
        if commit is None:
            if not fetch:
                raise RuntimeError(f"The baseline repository in {folder} does not have {ref}, use opp_checkout_test_baselines")
            # a branch or a tag can move; a commit can be new, or on no branch, as the head of a pull request is
            _git(folder, "fetch", "--quiet", "origin", ref)
            commit = _find_commit(folder, "FETCH_HEAD")
        return TestBaseline(commit, ref=ref)
    trailer = baseline.get("trailer")
    if not trailer:
        raise ValueError(f"The {kind} baseline entry of the project {simulation_project.get_name()} has no ref and no trailer")
    repository = _get_project_repository(simulation_project)
    project_hash = _find_commit(repository, project_commit)
    if project_hash is None:
        raise RuntimeError(f"The project repository {repository} has no commit {project_commit}")
    target, target_hash = _find_default_branch(repository, target)
    result = subprocess.run(["git", "merge-base", project_hash, target_hash], cwd=repository, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"The commit {project_hash} and {target} have no merge base in {repository}: the baseline needs the history of {target}, which a shallow clone does not have")
    base = result.stdout.strip()
    if fetch:
        _git(folder, "fetch", "--quiet", "origin")
    branch, _ = _find_default_branch(folder)
    marks = read_marks(folder, branch)
    marked = _find_marked_ancestor(repository, base, trailer, marks)
    if marked:
        master = marks[marked]
    else:
        old = _find_old_ref(simulation_project, repository, base, kind)
        if old is None:
            raise RuntimeError(f"No mark of the {kind} baseline repository names an ancestor of {base}, and no ancestor has a ref")
        master = old[1]
    _ensure_commit(folder, master, fetch)
    found = _find_pin(repository, base, project_hash, trailer)
    if found is None:
        return TestBaseline(master, project_hash, target=target, base=base, marked=marked, master=master)
    cause, pin = found
    _ensure_commit(folder, pin, fetch)
    commit, rebased = rebase_baseline_branch(folder, pin, master, branch)
    return TestBaseline(commit, project_hash, target=target, base=base, marked=marked, master=master, cause=cause, pin=pin, rebased=rebased)

def checkout_test_baseline(kind, simulation_project=None, target=None, project_commit="HEAD"):
    """
    Checks out the baseline repository of one test kind at the baseline of a commit of the simulation project.

    The function makes a clone when the folder does not exist. In a clone that exists, the function gets
    the baseline commit when the clone does not have it, and moves the checkout to that commit. A checkout
    that is already at the commit stays as it is, also on its branch. The function never discards a local
    change: git stops when the checkout would overwrite one.

    With the ``ref`` form, the baseline is the ref. With the ``trailer`` form, :py:func:`resolve_test_baseline`
    finds it. When the declaration has neither of them, a new clone is at the head of the default branch, and
    a clone that exists does not change.

    Parameters:
        kind (str):
            The test kind, for example ``"statistical"`` or ``"chart"``.

        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>`):
            The project that declares the baseline. If unspecified, then the default simulation project is used.

        target (str):
            The target branch of the project for the ``trailer`` form, see :py:func:`resolve_test_baseline`.

        project_commit (str):
            The commit of the project whose baseline the ``trailer`` form gives. The default is ``HEAD``. Another
            commit serves a tree that has the changes of that commit, for example a parent with a patch.

    Returns (str):
        the full hash of the commit that the checkout is at.
    """
    simulation_project = _get_simulation_project(simulation_project)
    baseline = _get_declared_baseline(kind, simulation_project)
    declared = baseline.get("ref") or baseline.get("trailer")
    folder = _get_checkout_folder(kind, simulation_project)
    is_new = not _is_git_checkout(folder)
    if is_new:
        if os.path.isdir(folder) and os.listdir(folder):
            raise RuntimeError(f"The {kind} baseline folder {folder} exists and is not a git checkout")
        parent_folder = os.path.dirname(folder)
        os.makedirs(parent_folder, exist_ok=True)
        _logger.info(f"Cloning the {kind} baseline repository {baseline['repository']} into {folder}")
        _git(parent_folder, "clone", "--quiet", *(["--no-checkout"] if declared else []), get_test_baseline_url(baseline["repository"]), folder)
    if declared:
        test_baseline = resolve_test_baseline(kind, simulation_project=simulation_project, target=target, project_commit=project_commit)
        for line in test_baseline.get_description():
            _logger.info(f"The {kind} baseline: {line}")
        if is_new or _find_commit(folder, "HEAD") != test_baseline.commit:
            _git(folder, "checkout", "--quiet", "--detach", test_baseline.commit)
    return _find_commit(folder, "HEAD")

def checkout_test_baselines(kinds=None, simulation_project=None, target=None, project_commit="HEAD"):
    """
    Checks out the baseline repositories of the simulation project at the baselines of one of its commits.

    Parameters:
        kinds (list of str):
            The test kinds. If unspecified, then all kinds that declare a baseline repository are used.

        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>`):
            The project that declares the baselines. If unspecified, then the default simulation project is used.

        target (str):
            The target branch of the project for the ``trailer`` form, see :py:func:`resolve_test_baseline`.

        project_commit (str):
            The commit of the project whose baselines the ``trailer`` form gives. The default is ``HEAD``.

    Returns (dict):
        the full hash of the commit of each checkout, by test kind.
    """
    simulation_project = _get_simulation_project(simulation_project)
    return {kind: checkout_test_baseline(kind, simulation_project=simulation_project, target=target, project_commit=project_commit) for kind in kinds or get_test_baseline_kinds(simulation_project)}

def check_test_baseline(kind, simulation_project=None, baseline_simulation_project=None, **kwargs):
    """
    Reports the commit of the baseline checkout of one test kind, and gives a warning when the checkout is
    not at the commit that the simulation project declares. The function changes nothing: a test must not
    move a checkout that can hold the work of the user.

    With the ``trailer`` form, the function compares the files of the checkout with the files of the
    baseline of the HEAD commit of the simulation project. It fetches nothing.

    Parameters:
        kind (str):
            The test kind, for example ``"statistical"`` or ``"chart"``.

        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>`):
            The project that declares the baseline. If unspecified, then the default simulation project is used.

        baseline_simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>`):
            The project whose root folder holds the checkout. If unspecified, then the simulation project is used.

    Returns (str or None):
        the full hash of the commit of the checkout, or None when the kind declares no baseline repository
        or the folder is not a git checkout.
    """
    simulation_project = _get_simulation_project(simulation_project)
    baseline = simulation_project.get_test_baseline(kind)
    if not baseline:
        return None
    ref = baseline.get("ref")
    folder = _get_checkout_folder(kind, simulation_project, baseline_simulation_project)
    if not _is_git_checkout(folder):
        _logger.warning(f"The {kind} baseline repository {baseline['repository']} is not checked out in {folder}, use opp_checkout_test_baselines")
        return None
    commit = _find_commit(folder, "HEAD")
    if commit is None:
        # for example a worktree whose repository is not there, as in a container that has only the files
        _logger.warning(f"Cannot read the commit of the {kind} baseline checkout in {folder}, the results compare with files of an unknown commit")
        return None
    try:
        has_changes = bool(_git(folder, "status", "--porcelain", "--untracked-files=no"))
    except RuntimeError:
        has_changes = False
    _logger.info(f"The {kind} baseline is {baseline['repository']} at {commit}" + (" with local changes" if has_changes else ""))
    if ref and _full_hash_pattern.match(ref) and commit != ref:
        _logger.warning(f"The {kind} baseline checkout in {folder} is at {commit}, but the project declares {ref}, use opp_checkout_test_baselines")
    elif baseline.get("trailer") and not ref:
        try:
            test_baseline = resolve_test_baseline(kind, simulation_project=simulation_project, baseline_simulation_project=baseline_simulation_project, fetch=False)
        except (RuntimeError, ValueError) as e:
            _logger.warning(f"Cannot find the {kind} baseline of the project commit, the results compare with the checkout at {commit}: {e}")
        else:
            # a commit with the same files is the same baseline, for example the commit that the landing job made
            if _git(folder, "rev-parse", commit + "^{tree}") != _git(folder, "rev-parse", test_baseline.commit + "^{tree}"):
                _logger.warning(f"The {kind} baseline checkout in {folder} is at {commit}, but the baseline of the project commit is {test_baseline.commit}, use opp_checkout_test_baselines")
    return commit
