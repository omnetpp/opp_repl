"""
This module checks out the baseline repositories of the tests of a simulation project.

A test kind can compare its results with stored results that are in another git repository. The
``baseline`` entry of the kind in the ``test_parameters`` of the ``.opp`` file declares that
repository: ``repository`` is its URL or its ``owner/name`` on GitHub, ``folder`` is the folder of
the clone below the project root, and ``ref`` is the commit to use. With a full commit hash as
``ref``, each commit of the simulation project names the exact stored results that it passes with.

The main function is :py:func:`checkout_test_baselines`. A test never changes a baseline checkout:
:py:func:`check_test_baseline` only reports a checkout that is not at the declared commit.
"""

import logging
import os
import re
import subprocess

_logger = logging.getLogger(__name__)

_full_hash_pattern = re.compile(r"^[0-9a-f]{40}$")

def _git(folder, *args):
    """Runs a git command in the folder and returns its output. An error of git raises an exception with the message of git."""
    result = subprocess.run(["git", *args], cwd=folder, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {folder}:\n{result.stderr.strip()}")
    return result.stdout.strip()

def _find_commit(folder, name):
    """Returns the full hash of the commit that the name gives in the repository of the folder, or None."""
    result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", name + "^{commit}"], cwd=folder, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None

def _is_git_checkout(folder):
    # a folder below the project root with no .git entry of its own is a part of the project repository
    return os.path.exists(os.path.join(folder, ".git"))

def _get_simulation_project(simulation_project):
    if simulation_project is None:
        from opp_repl.simulation.workspace import get_default_simulation_project  # lazy: avoid the test/* import cycle
        simulation_project = get_default_simulation_project()
    return simulation_project

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

def checkout_test_baseline(kind, simulation_project=None):
    """
    Checks out the baseline repository of one test kind at the commit that the simulation project declares.

    The function makes a clone when the folder does not exist. In a clone that exists, the function gets
    the declared commit when the clone does not have it, and moves the checkout to that commit. A checkout
    that is already at the commit stays as it is, also on its branch. The function never discards a local
    change: git stops when the checkout would overwrite one.

    When the declaration has no ``ref``, a new clone is at the head of the default branch, and a clone that
    exists does not change.

    Parameters:
        kind (str):
            The test kind, for example ``"statistical"`` or ``"chart"``.

        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>`):
            The project that declares the baseline. If unspecified, then the default simulation project is used.

    Returns (str):
        the full hash of the commit that the checkout is at.
    """
    simulation_project = _get_simulation_project(simulation_project)
    baseline = simulation_project.get_test_baseline(kind)
    if not baseline:
        raise ValueError(f"The {kind} tests of the project {simulation_project.get_name()} declare no baseline repository")
    ref = baseline.get("ref")
    folder = simulation_project.get_full_path(baseline.get("folder") or ".")
    is_new = not _is_git_checkout(folder)
    if is_new:
        if os.path.isdir(folder) and os.listdir(folder):
            raise RuntimeError(f"The {kind} baseline folder {folder} exists and is not a git checkout")
        parent_folder = os.path.dirname(folder)
        os.makedirs(parent_folder, exist_ok=True)
        _logger.info(f"Cloning the {kind} baseline repository {baseline['repository']} into {folder}")
        _git(parent_folder, "clone", "--quiet", *(["--no-checkout"] if ref else []), get_test_baseline_url(baseline["repository"]), folder)
    if ref:
        commit = _find_commit(folder, ref) if _full_hash_pattern.match(ref) else None
        if commit is None:
            # a branch or a tag can move; a commit can be new, or on no branch, as the head of a pull request is
            _git(folder, "fetch", "--quiet", "origin", ref)
            commit = _find_commit(folder, "FETCH_HEAD")
        if is_new or _find_commit(folder, "HEAD") != commit:
            _git(folder, "checkout", "--quiet", "--detach", commit)
    return _find_commit(folder, "HEAD")

def checkout_test_baselines(kinds=None, simulation_project=None):
    """
    Checks out the baseline repositories of the simulation project at the commits that the project declares.

    Parameters:
        kinds (list of str):
            The test kinds. If unspecified, then all kinds that declare a baseline repository are used.

        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>`):
            The project that declares the baselines. If unspecified, then the default simulation project is used.

    Returns (dict):
        the full hash of the commit of each checkout, by test kind.
    """
    simulation_project = _get_simulation_project(simulation_project)
    return {kind: checkout_test_baseline(kind, simulation_project=simulation_project) for kind in kinds or get_test_baseline_kinds(simulation_project)}

def check_test_baseline(kind, simulation_project=None, baseline_simulation_project=None, **kwargs):
    """
    Reports the commit of the baseline checkout of one test kind, and gives a warning when the checkout is
    not at the commit that the simulation project declares. The function changes nothing: a test must not
    move a checkout that can hold the work of the user.

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
    folder = (baseline_simulation_project or simulation_project).get_full_path(baseline.get("folder") or ".")
    if not _is_git_checkout(folder):
        _logger.warning(f"The {kind} baseline repository {baseline['repository']} is not checked out in {folder}, use opp_checkout_test_baselines")
        return None
    commit = _find_commit(folder, "HEAD")
    has_changes = bool(_git(folder, "status", "--porcelain", "--untracked-files=no"))
    _logger.info(f"The {kind} baseline is {baseline['repository']} at {commit}" + (" with local changes" if has_changes else ""))
    if ref and _full_hash_pattern.match(ref) and commit != ref:
        _logger.warning(f"The {kind} baseline checkout in {folder} is at {commit}, but the project declares {ref}, use opp_checkout_test_baselines")
    return commit
