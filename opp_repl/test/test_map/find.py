"""
Finds the test map for a change (see the test selection plan of opp_repl,
``plan/pending/test-selection.md``, section 8.4). A map describes its map commit A, and the
selection is correct with any A, but a map whose commit is near the base B selects fewer tests.

The candidates are the map of a folder (``--map``), the local map of the project
(``coverage/test-map/map``), and the maps in the history of a map repository: the checkout of
``test_parameters["coverage"]["baseline"]`` of the project, whose ``map/`` folder holds the map of
each weekly run. Of the candidates whose map commit is an ancestor of B, the one with the fewest
commits from A to B wins.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile

from opp_repl.test.test_map.changes import is_commit, _git
from opp_repl.test.test_map.writer import get_default_test_map_folder

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

# the folder of the map in a map repository
MAP_REPOSITORY_FOLDER = "map"

def get_map_repository_folder(simulation_project):
    """Returns the checkout of the map repository of the project (``test_parameters["coverage"]["baseline"]``), or None."""
    baseline = (simulation_project.test_parameters.get("coverage") or {}).get("baseline")
    if not baseline:
        return None
    folder = simulation_project.get_full_path(baseline.get("folder") or "coverage-map")
    return folder if os.path.isdir(os.path.join(folder, ".git")) or os.path.isfile(os.path.join(folder, ".git")) else None

def _get_distance(root_folder, map_commit, base):
    # the number of commits from the map commit to the base, or None if the map commit is not an ancestor of the base
    if not map_commit or not is_commit(root_folder, map_commit):
        return None
    if _git(root_folder, "merge-base", "--is-ancestor", map_commit, base, check=False).returncode != 0:
        return None
    return int(_git(root_folder, "rev-list", "--count", f"{map_commit}..{base}").stdout.strip())

def find_repository_map(repository_folder, root_folder, base, cache_folder, max_versions=200):
    """
    Returns ``(folder, distance)`` of the newest version of the map in the history of the map
    repository *repository_folder* whose map commit is an ancestor of *base* in the repository of
    *root_folder*, or None. The version is extracted into *cache_folder* once.
    """
    commits = _git(repository_folder, "log", "--format=%H", f"-{max_versions}", "HEAD", "--", f"{MAP_REPOSITORY_FOLDER}/header.json", check=False).stdout.split()
    for commit in commits:
        text = _git(repository_folder, "show", f"{commit}:{MAP_REPOSITORY_FOLDER}/header.json", check=False).stdout
        try:
            header = json.loads(text)
        except ValueError:
            continue
        distance = _get_distance(root_folder, header.get("commit"), base)
        if distance is None:
            continue
        folder = os.path.join(cache_folder, commit[:12])
        if not os.path.exists(os.path.join(folder, "header.json")):
            os.makedirs(cache_folder, exist_ok=True)
            temporary = tempfile.mkdtemp(dir=cache_folder)
            try:
                archive = subprocess.run(["git", "-C", repository_folder, "archive", commit, MAP_REPOSITORY_FOLDER], capture_output=True, check=True).stdout
                subprocess.run(["tar", "-x", "-C", temporary], input=archive, check=True)
                shutil.rmtree(folder, ignore_errors=True)
                os.replace(os.path.join(temporary, MAP_REPOSITORY_FOLDER), folder)
            finally:
                shutil.rmtree(temporary, ignore_errors=True)
        return folder, distance
    return None

def find_test_map(simulation_project, base, map_folder=None):
    """
    Returns the folder of the test map for the base commit *base*: *map_folder* if it holds a map, the
    best map of the history of *map_folder* if it is a map repository, else the best of the local map
    of the project and of the maps of its map repository (see the module documentation). Returns the
    local map folder if no candidate qualifies, so that the caller reports it.
    """
    root_folder = simulation_project.get_full_path(".")
    cache_folder = get_default_test_map_folder(simulation_project, "cache")
    if map_folder:
        map_folder = os.path.abspath(map_folder)
        if os.path.exists(os.path.join(map_folder, "header.json")) or not os.path.exists(os.path.join(map_folder, ".git")):
            return map_folder
        found = find_repository_map(map_folder, root_folder, base, cache_folder)
        if found is None:
            raise Exception(f"The map repository {map_folder} has no map whose commit is an ancestor of {base[:10]}")
        return found[0]
    candidates = []
    local_folder = get_default_test_map_folder(simulation_project, "map")
    if os.path.exists(os.path.join(local_folder, "header.json")):
        with open(os.path.join(local_folder, "header.json")) as f:
            distance = _get_distance(root_folder, json.load(f).get("commit"), base)
        if distance is not None:
            candidates.append((distance, 0, local_folder))
    repository_folder = get_map_repository_folder(simulation_project)
    if repository_folder:
        found = find_repository_map(repository_folder, root_folder, base, cache_folder)
        if found:
            candidates.append((found[1], 1, found[0]))
    if not candidates:
        return local_folder
    distance, _, folder = min(candidates)
    _logger.info(f"The test map {folder} is {distance} commits older than the base {base[:10]}")
    return folder
