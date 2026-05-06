import json
import logging
import os
import pathlib
import subprocess

from opp_repl.simulation.project import *
from opp_repl.simulation.task import *
from opp_repl.test.feature import read_xml_file, get_package_folder, get_features, get_feature_to_packages, get_packages, get_package_to_feature

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

_simulation_task_dependency_stores = dict()

class SimulationTaskDependencyStore:
    """Maps source files/packages/features to affected simulation configs.
    Follows the FingerprintStore read/write/ensure pattern."""

    def __init__(self, simulation_project, file_name):
        self.simulation_project = simulation_project
        self.file_name = file_name
        self.entries = None

    def read(self):
        _logger.info(f"Reading simulation task dependencies from {self.file_name}")
        file = open(self.file_name, "r")
        self.entries = json.load(file)
        file.close()

    def write(self):
        _logger.info(f"Writing simulation task dependencies to {self.file_name}")
        file = open(self.file_name, "w")
        json.dump(self.entries, file, indent=True)
        file.close()

    def ensure(self):
        if os.path.exists(self.file_name):
            self.read()
        else:
            raise FileNotFoundError(
                f"Dependency store '{self.file_name}' not found. "
                f"Run update_simulation_task_dependencies() first.")

    def get_entries(self):
        if self.entries is None:
            self.ensure()
        return self.entries

    def build_entries(self, simulation_results):
        """Build entries from simulation results (with used_types).
        Populates self.entries with the dependency mappings."""
        oppfeatures_path = self.simulation_project.get_full_path(".oppfeatures")
        if os.path.exists(oppfeatures_path):
            oppfeatures = read_xml_file(oppfeatures_path)
            feature_to_packages = get_feature_to_packages(oppfeatures)
            packages = get_packages(oppfeatures)
            feature_required_by = _get_feature_required_by(oppfeatures)
        else:
            feature_to_packages = {}
            packages = []
            feature_required_by = {}
        package_to_feature = get_package_to_feature(feature_to_packages)
        folder_to_package = _get_folder_to_package(packages)
        packages_set = set(packages)
        simulation_entries = []
        for simulation_result in simulation_results.results:
            task = simulation_result.task
            # determine which features this simulation config uses
            simulation_features = set()
            for used_type in simulation_result.used_types:
                parts = used_type.split(".")
                for i in range(len(parts) - 1, 0, -1):
                    candidate = ".".join(parts[:i])
                    if candidate in packages_set:
                        if candidate in package_to_feature:
                            simulation_features.add(package_to_feature[candidate])
                        break
            simulation_entries.append({
                "working_directory": task.simulation_config.working_directory,
                "ini_file": task.simulation_config.ini_file,
                "config": task.simulation_config.config,
                "run_number": task.run_number,
                "used_features": sorted(list(simulation_features))
            })
        simulation_entries.sort(key=lambda e: (e["working_directory"], e["ini_file"], e["config"], e["run_number"]))
        self.entries = {
            "feature_to_packages": {f: sorted(p) for f, p in feature_to_packages.items()},
            "packages": sorted(packages),
            "folder_to_package": folder_to_package,
            "package_to_feature": package_to_feature,
            "feature_required_by": {f: sorted(deps) for f, deps in feature_required_by.items()},
            "simulations": simulation_entries
        }

    def get_affected_simulation_config_keys(self, modified_files):
        """Given modified file paths (relative to project root), returns a set of
        (working_directory, ini_file, config) tuples for affected simulation configs.

        If any modified file is in a directory not belonging to any feature (core change),
        returns None to indicate all configs are affected."""
        entries = self.get_entries()
        folder_to_package = entries["folder_to_package"]
        package_to_feature = entries["package_to_feature"]
        affected_features = set()
        for modified_file in modified_files:
            path = pathlib.Path(modified_file).parent
            matched = False
            while str(path) != ".":
                folder = str(path)
                if folder in folder_to_package:
                    package = folder_to_package[folder]
                    if package in package_to_feature:
                        affected_features.add(package_to_feature[package])
                    matched = True
                    break
                path = path.parent
            if not matched:
                _logger.warning("Modified file in directory not belonging to any feature (core change, all configs affected): %s", modified_file)
                return None
        feature_required_by = entries.get("feature_required_by", {})
        expanded_features = set(affected_features)
        queue = list(affected_features)
        while queue:
            feature = queue.pop()
            for dependent in feature_required_by.get(feature, []):
                if dependent not in expanded_features:
                    expanded_features.add(dependent)
                    queue.append(dependent)
        affected_keys = set()
        for entry in entries["simulations"]:
            entry_features = set(entry["used_features"])
            if expanded_features & entry_features:
                affected_keys.add((entry["working_directory"], entry["ini_file"], entry["config"]))
        return affected_keys

    def get_modified_files_for_git_commit(self, commit):
        """Returns list of modified files (relative to project root) for a single git commit."""
        root = self.simulation_project.get_full_path(".")
        result = subprocess.run(["git", "diff-tree", "--no-commit-id", "-r", "--name-only", commit],
                                cwd=root, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception("git diff-tree failed: " + result.stderr)
        return [f for f in result.stdout.strip().split("\n") if f]

    def get_modified_files_for_git_range(self, from_commit, to_commit):
        """Returns list of modified files (relative to project root) for a range of git commits."""
        root = self.simulation_project.get_full_path(".")
        result = subprocess.run(["git", "diff", "--name-only", from_commit, to_commit],
                                cwd=root, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception("git diff failed: " + result.stderr)
        return [f for f in result.stdout.strip().split("\n") if f]

def _get_feature_required_by(oppfeatures):
    """Parse requires attribute from .oppfeatures and build reverse map.
    Returns {feature: [features that require it]}."""
    result = {}
    for feature_dom in oppfeatures.documentElement.getElementsByTagName("feature"):
        feature_id = str(feature_dom.getAttribute("id"))
        requires_str = feature_dom.getAttribute("requires").strip()
        if requires_str:
            for required_feature in requires_str.split():
                if required_feature not in result:
                    result[required_feature] = []
                result[required_feature].append(feature_id)
    return result

def _get_folder_to_package(packages):
    """Invert of get_package_folder(): returns {directory: package}"""
    result = {}
    for package in packages:
        folder = get_package_folder(package)
        result[folder] = package
    return result

def get_simulation_task_dependency_store(simulation_project):
    """Get cached store instance for a project (like get_correct_fingerprint_store)."""
    if simulation_project not in _simulation_task_dependency_stores:
        _simulation_task_dependency_stores[simulation_project] = SimulationTaskDependencyStore(
            simulation_project,
            simulation_project.get_full_path(simulation_project.dependency_store))
    return _simulation_task_dependency_stores[simulation_project]

def update_simulation_task_dependencies(simulation_project=None, simulation_results=None, mode="release", **kwargs):
    """Build (or rebuild) dependencies and save to project's dependency_store.
    Runs all simulations with --print-instantiated-ned-types=true (like update_oppfeatures)."""
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    if simulation_results is None:
        simulation_results = run_simulations(simulation_project=simulation_project, mode=mode, run_number=0, append_args=["--print-instantiated-ned-types=true"], **kwargs)
    store = get_simulation_task_dependency_store(simulation_project)
    store.build_entries(simulation_results)
    store.write()
    return store
update_simulation_task_dependencies.__signature__ = combine_signatures(update_simulation_task_dependencies, run_simulations)
