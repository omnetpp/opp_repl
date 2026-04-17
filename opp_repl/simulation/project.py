"""
This module provides abstractions for simulation projects.

The main functions are:

- :py:func:`get_simulation_project`:
- :py:func:`get_default_simulation_project`:

In general, it's a good idea to use the default project, because it makes calling the various functions easier and in
most cases there's only one simulation project is worked on. The default simulation project is automatically set to the
one above the current working directory when the omnetpp.repl package is loaded, but it can be overridden by the user
later.
"""

import builtins
import glob
import hashlib
import json
import logging
import multiprocessing
import os
import re
import shutil
import socket
import subprocess

try:
    from omnetpp.runtime.omnetpp import *
except:
    pass

from opp_repl.common.util import *
from opp_repl.simulation.config import *

_logger = logging.getLogger(__name__)

class OmnetppProject:
    """
    Represents a specific OMNeT++ installation with all its options. Used to locate the OMNeT++ root directory,
    resolve executables like ``opp_run``, and determine library suffixes for different build modes.

    Optionally supports overlay builds via fuse-overlayfs.  When *overlay_key*
    is given, an :py:class:`OverlayMount` is created and all paths resolve to
    the overlay's merged directory instead of the original source tree.
    """

    def __init__(self, environment_variable="__omnetpp_root_dir", root_folder=None,
                 overlay_key=None, build_root=None):
        """
        Initializes a new OMNeT++ project.

        Parameters:
            environment_variable (string):
                The operating system environment variable specifying the root folder of the OMNeT++ installation.

            root_folder (string or None):
                The root folder of the OMNeT++ installation. If specified, it is used instead of the environment variable.

            overlay_key (str or None):
                If set, enables overlay mode.  An :py:class:`OverlayMount` is
                created with this key and all paths resolve to the overlay's
                merged directory.

            build_root (str or None):
                Override for the overlay build root directory.
        """
        self.environment_variable = environment_variable
        self.root_folder = root_folder
        self._overlay = None
        if overlay_key is not None:
            from opp_repl.simulation.overlay import OverlayMount
            source_root = self._resolve_source_root()
            if source_root is None:
                raise RuntimeError("Cannot create overlay: root path is not set")
            self._overlay = OverlayMount(source_root, overlay_key, build_root)
            self.root_folder = self._overlay.merged_path

    def _resolve_source_root(self):
        if self.root_folder is not None:
            return os.path.abspath(self.root_folder)
        elif self.environment_variable is not None and self.environment_variable in os.environ:
            return os.path.abspath(os.environ[self.environment_variable])
        else:
            return None

    def __repr__(self):
        overlay = f", overlay={self._overlay.overlay_key!r}" if self._overlay else ""
        return f"OmnetppProject(environment_variable={self.environment_variable!r}, root_folder={self.root_folder!r}{overlay})"

    def get_root_path(self):
        if self.root_folder is not None:
            return os.path.abspath(self.root_folder)
        elif self.environment_variable is not None and self.environment_variable in os.environ:
            return os.path.abspath(os.environ[self.environment_variable])
        else:
            return None

    def get_library_suffix(self, mode="release"):
        if mode == "release":
            return "_release"
        elif mode == "debug":
            return "_dbg"
        elif mode == "sanitize":
            return "_sanitize"
        elif mode == "coverage":
            return "_coverage"
        elif mode == "profile":
            return "_profile"
        else:
            raise Exception(f"Unknown mode: {mode}")

    def get_executable(self, mode="release"):
        root = self.get_root_path()
        if root is None:
            return None
        suffix = self.get_library_suffix(mode=mode)
        return os.path.abspath(os.path.join(root, "bin/opp_run" + suffix))

    def build(self, mode="release"):
        self.ensure_mounted()
        root = self.get_root_path()
        if root is None:
            raise RuntimeError("Cannot build OMNeT++: root path is not set")
        env = os.environ.copy()
        bin_dir = os.path.join(root, "bin")
        lib_dir = os.path.join(root, "lib")
        if bin_dir not in env.get("PATH", "").split(os.pathsep):
            env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        if lib_dir not in env.get("LD_LIBRARY_PATH", "").split(os.pathsep):
            env["LD_LIBRARY_PATH"] = lib_dir + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        args = ["make", "MODE=" + mode, "-j", str(multiprocessing.cpu_count())]
        _logger.info("Building OMNeT++ in %s mode at %s", mode, root)
        run_command_with_logging(args, cwd=root, env=env, error_message="Building OMNeT++ failed")

    def ensure_mounted(self):
        if self._overlay is not None:
            self._overlay.mount()

    def unmount(self):
        if self._overlay is not None:
            self._overlay.unmount()

    def is_mounted(self):
        if self._overlay is not None:
            return self._overlay.is_mounted()
        return False

    def clean(self):
        if self._overlay is not None:
            self._overlay.clean()

_default_omnetpp_project = None

def get_default_omnetpp_project():
    return _default_omnetpp_project

def set_default_omnetpp_project(project):
    global _default_omnetpp_project
    _default_omnetpp_project = project

class SimulationProject:
    """
    Represents a simulation project that usually comes with its own modules and their C++ implementation, and also with
    several example simulations.

    Please note that undocumented features are not supposed to be called by the user.
    """

    def __init__(self, name, version=None, git_hash=None, git_diff_hash=None, folder_environment_variable=None, root_folder=None, folder=".", omnetpp_project=None,
                 bin_folder=".", library_folder=".", executables=None, dynamic_libraries=None, static_libraries=None, build_types=["dynamic library"],
                 ned_folders=["."], ned_exclusions=[], ini_file_folders=["."], python_folders=["python"], image_folders=["."],
                 include_folders=["."], cpp_folders=["."], cpp_defines=[], msg_folders=["."],
                 media_folder=".", statistics_folder=".", fingerprint_store="fingerprint.json", speed_store="speed.json",
                 used_projects=[], external_bin_folders=[], external_library_folders=[], external_libraries=[], external_include_folders=[],
                 simulation_configs=None, overlay_key=None, build_root=None, **kwargs):
        """
        Initializes a new simulation project.

        Parameters:
            name (string):
                The human readable name of the simulation project.

            version (string or None):
                The version string.

            git_hash (string or None):
                The git hash of the corresponding git repository for the specific version.

            git_diff_hash (string):
                The hash of the local modifications on top of the clean checkout of from the git repository.

            folder_environment_variable (string):
                The operating system environment variable.

            root_folder (string or None):
                The root folder of the simulation project. If specified, it is used instead of the folder_environment_variable environment variable.

            omnetpp_project (:py:class:`OmnetppProject` or None):
                The OMNeT++ project representing the OMNeT++ installation to use.
                If unspecified, defaults to the global ``default_omnetpp_project``
                when an executable is needed (e.g. for running simulations).

            folder (string):
                The directory of the simulation project relative to the value of the folder_environment_variable attribute.

            bin_folder (string):
                The directory of the binary output files relative to the value of the folder_environment_variable attribute.

            library_folder (string):
                The directory of the library output files relative to the value of the folder_environment_variable attribute.

            executables (List of strings):
                The list of executables that are built.

            dynamic_libraries (List of strings):
                The list of dynamic libraries that are built.

            static_libraries (List of strings):
                TODO

            build_types (List of strings):
                The list of build output types. Valid values are "executable", "dynamic library", "static library".

            ned_folders (List of strings):
                The list of folder_environment_variable relative directories for NED files.

            ned_exclusions (List of strings):
                The list of excluded NED packages.

            ini_file_folders (List of strings):
                The list of folder_environment_variable relative directories for INI files.

            python_folders (List of strings):
                The list of folder_environment_variable relative directories for Python source files.

            image_folders (List of strings):
                The list of folder_environment_variable relative directories for image files.

            include_folders (List of strings):
                The list of folder_environment_variable relative directories for C++ include files.

            cpp_folders (List of strings):
                The list of folder_environment_variable relative directories for C++ source files.

            cpp_defines (List of strings):
                The list of C++ macro definitions that are passed to the C++ compiler.

            msg_folders (List of strings):
                The list of folder_environment_variable relative directories for MSG files.

            media_folder (String):
                The relative path of chart image files for chart tests.

            statistics_folder (String):
                The relative path of scalar statistic result files for statistical tests.

            fingerprint_store (String):
                The relative path of the JSON fingerprint store for fingerprint tests.

            speed_store (String):
                The relative path of the JSON measurement store for speed tests.

            used_projects (List of strings):
                The list of used simulation project names.

            external_bin_folders (List of strings):
                The list of absolute directories that contains external binaries.

            external_library_folders (List of strings):
                The list of absolute directories that contains external libraries.

            external_libraries (List of strings):
                The list external library names.

            external_include_folders (List of strings):
                The list of absolute directories that contains external C++ include files.

            simulation_configs (List of :py:class:`SimulationConfig <opp_repl.simulation.config.SimulationConfig>`):
                The list of simulation configs available in this simulation project.

            overlay_key (str or None):
                If set, enables overlay mode.  An :py:class:`OverlayMount` is
                created with this key and all paths resolve to the overlay's
                merged directory.

            build_root (str or None):
                Override for the overlay build root directory.

            kwargs (dict):
                Ignored.
        """
        self.name = name
        self.version = version
        self.folder_environment_variable = folder_environment_variable
        self.root_folder = root_folder
        self.folder = folder
        self.omnetpp_project = omnetpp_project
        # TODO this is commented out because it runs subprocesses, and it even does this from the IDE when some completely unrelated modules are loaded, sigh!
        # self.git_hash = git_hash or run_command_with_logging(["git", "rev-parse", "HEAD"], cwd=self.get_full_path(".")).stdout.strip()
        # if git_diff_hash:
        #     self.git_diff_hash = git_diff_hash
        # else:
        #     git_diff_hasher = hashlib.sha256()
        #     git_diff_hasher.update(run_command_with_logging(["git", "diff", "--quiet"], cwd=self.get_full_path(".")).stdout)
        #     self.git_diff_hash = git_diff_hasher.digest().hex()
        self.bin_folder = bin_folder
        self.library_folder = library_folder
        self.executables = [name] if executables is None else executables
        self.dynamic_libraries = [name] if dynamic_libraries is None else dynamic_libraries
        self.static_libraries = [name] if static_libraries is None else static_libraries
        self.build_types = build_types
        self.ned_folders = ned_folders
        self.ned_exclusions = ned_exclusions
        self.ini_file_folders = ini_file_folders
        self.python_folders = python_folders
        self.image_folders = image_folders
        self.include_folders = include_folders
        self.cpp_folders = cpp_folders
        self.cpp_defines = cpp_defines
        self.msg_folders = msg_folders
        self.media_folder = media_folder
        self.statistics_folder = statistics_folder
        self.fingerprint_store = fingerprint_store
        self.speed_store = speed_store
        self.used_projects = used_projects
        self.external_bin_folders = external_bin_folders
        self.external_library_folders = external_library_folders
        self.external_libraries = external_libraries
        self.external_include_folders = external_include_folders
        self.simulation_configs = simulation_configs
        self.binary_simulation_distribution_file_paths = None
        self._overlay = None
        if overlay_key is not None:
            from opp_repl.simulation.overlay import OverlayMount
            source_root = self.get_root_path()
            if source_root is None:
                raise RuntimeError("Cannot create overlay: root path is not set")
            self._overlay = OverlayMount(source_root, overlay_key, build_root)
            self.root_folder = self._overlay.merged_path
            self.simulation_configs = None

    def __repr__(self):
        return repr(self, ["name", "version", "git_hash", "git_diff_hash"])

    def get_name(self):
        return os.path.basename(self.get_full_path("."))

    def get_hash(self, binary=True, **kwargs):
        hasher = hashlib.sha256()
        if binary:
            for file_path in self.get_binary_simulation_distribution_file_paths():
                hasher.update(get_file_hash(file_path))
        else:
            raise Exception("Not implemented")
        return hasher.digest()

    def get_env(self):
        env = os.environ.copy()
        opp = self.get_omnetpp_project()
        opp_root = opp.get_root_path() if opp else None
        if opp_root is not None:
            bin_dir = os.path.join(opp_root, "bin")
            lib_dir = os.path.join(opp_root, "lib")
            if bin_dir not in env.get("PATH", "").split(os.pathsep):
                env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
            if lib_dir not in env.get("LD_LIBRARY_PATH", "").split(os.pathsep):
                env["LD_LIBRARY_PATH"] = lib_dir + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        ws = getattr(self, '_workspace', None) or get_default_simulation_workspace()
        for used_project_name in self.used_projects:
            used_project = ws.get_simulation_project(used_project_name, None)
            used_root = used_project.get_root_path()
            if used_root is not None:
                env_var = used_project_name.upper().replace("-", "_") + "_ROOT"
                env[env_var] = used_root
                used_lib_dir = used_project.get_library_folder_full_path()
                if used_lib_dir and used_lib_dir not in env.get("LD_LIBRARY_PATH", "").split(os.pathsep):
                    env["LD_LIBRARY_PATH"] = used_lib_dir + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        return env

    def get_environment_variable_relative_path(self, enviroment_variable, path):
        return os.path.abspath(os.path.join(os.environ[enviroment_variable], path)) if enviroment_variable in os.environ else None

    def get_root_path(self):
        if self.root_folder is not None:
            return os.path.abspath(self.root_folder)
        elif self.folder_environment_variable is not None and self.folder_environment_variable in os.environ:
            return os.path.abspath(os.environ[self.folder_environment_variable])
        else:
            return None

    def get_full_path(self, path):
        root = self.get_root_path()
        base = os.path.join(root, self.folder) if root is not None else None
        return os.path.abspath(os.path.join(base, path)) if base is not None else None

    def get_relative_path(self, path):
        root = self.get_root_path()
        base = os.path.join(root, self.folder) if root is not None else None
        return os.path.relpath(path, base)

    def get_omnetpp_project(self):
        if isinstance(self.omnetpp_project, str):
            ws = getattr(self, '_workspace', None) or get_default_simulation_workspace()
            self.omnetpp_project = ws.get_omnetpp_project_by_name(self.omnetpp_project)
        return self.omnetpp_project or get_default_omnetpp_project()

    def get_executable(self, mode="release"):
        dynamic_loading = self.build_types[0] == "dynamic library"
        if dynamic_loading:
            return self.get_omnetpp_project().get_executable(mode=mode)
        else:
            executable = os.path.join(self.folder, self.executables[0])
            root = self.get_root_path()
            return os.path.abspath(os.path.join(root, executable)) if root is not None else None

    def get_library_folder_full_path(self):
        return self.get_full_path(self.library_folder)

    def get_dynamic_libraries_for_running(self):
        result = []
        if self.build_types[0] == "dynamic library":
            for library in self.dynamic_libraries:
                result.append(os.path.join(self.library_folder, library))
            for used_project in self.used_projects:
                simulation_project = get_simulation_project(used_project, None)
                result = result + list(map(simulation_project.get_full_path, simulation_project.get_dynamic_libraries_for_running()))
        return result

    def get_ned_folders_for_running(self):
        result = self.ned_folders
        for used_project in self.used_projects:
            simulation_project = get_simulation_project(used_project, None)
            result = result + list(map(simulation_project.get_full_path, simulation_project.get_ned_folders_for_running()))
        return result

    def get_multiple_args(self, option, elements):
        args = []
        for element in elements:
            args.append(option)
            args.append(element)
        return args

    def get_full_path_args(self, option, paths):
        return self.get_multiple_args(option, map(self.get_full_path, paths))

    def get_default_args(self):
        return [*self.get_full_path_args("-l", self.get_dynamic_libraries_for_running()), *self.get_full_path_args("-n", self.get_ned_folders_for_running()), *self.get_multiple_args("-x", self.ned_exclusions or self.get_ned_exclusions()), *self.get_full_path_args("--image-path", self.image_folders)]

    def get_ned_exclusions(self):
        nedexclusions_path = self.get_full_path(".nedexclusions")
        return [s.strip() for s in open(nedexclusions_path).readlines()] if os.path.exists(nedexclusions_path) else []

    def get_direct_include_folders(self):
        return list(map(lambda include_folder: self.get_full_path(include_folder), self.include_folders))

    def get_effective_include_folders(self):
        return self.get_direct_include_folders() + flatten(map(lambda used_project: get_simulation_project(used_project, None).get_direct_include_folders(), self.used_projects))

    def get_cpp_files(self):
        cpp_files = []
        for cpp_folder in self.cpp_folders:
            file_paths = list(filter(lambda file_path: not re.search(r"_m\.cc", file_path), glob.glob(self.get_full_path(os.path.join(cpp_folder, "**/*.cc")), recursive=True)))
            cpp_files = cpp_files + list(map(lambda file_path: self.get_relative_path(file_path), file_paths))
        return cpp_files

    def get_header_files(self):
        header_files = []
        for cpp_folder in self.cpp_folders:
            file_paths = list(filter(lambda file_path: not re.search(r"_m\.h", file_path), glob.glob(self.get_full_path(os.path.join(cpp_folder, "**/*.h")), recursive=True)))
            header_files = header_files + list(map(lambda file_path: self.get_relative_path(file_path), file_paths))
        return header_files

    def get_msg_files(self):
        msg_files = []
        for msg_folder in self.msg_folders:
            file_paths = glob.glob(self.get_full_path(os.path.join(msg_folder, "**/*.msg")), recursive=True)
            msg_files = msg_files + list(map(lambda file_path: self.get_relative_path(file_path), file_paths))
        return msg_files

    def build(self, mode="release", **kwargs):
        self.ensure_mounted()
        opp = self.get_omnetpp_project()
        if opp is not None:
            opp.build(mode=mode)
        import opp_repl.simulation.build
        opp_repl.simulation.build.build_project(simulation_project=self, mode=mode, **kwargs)

    def ensure_mounted(self):
        if self._overlay is not None:
            self._overlay.mount()

    def unmount(self):
        if self._overlay is not None:
            self._overlay.unmount()

    def is_mounted(self):
        if self._overlay is not None:
            return self._overlay.is_mounted()
        return False

    def clean(self):
        if self._overlay is not None:
            self._overlay.clean()

    # KLUDGE TODO replace this with a Python binding to the C++ configuration reader
    def collect_ini_file_simulation_configs(self, ini_path):
        def get_sim_time_limit(config_dicts, config):
            config_dict = config_dicts[config]
            if "sim_time_limit" in config_dict:
                return config_dict["sim_time_limit"]
            if "extends" in config_dict:
                extends = config_dict["extends"]
                for base_config in extends.split(","):
                    if base_config in config_dicts:
                        sim_time_limit = get_sim_time_limit(config_dicts, base_config)
                        if sim_time_limit:
                            return sim_time_limit
            return config_dicts["General"].get("sim_time_limit")
        def create_config_dict(config):
            return {"config": config, "abstract": False, "emulation": False, "expected_result": "DONE", "user_interface": None, "description": None, "network": None}
        num_runs_fast_regex = re.compile(r"(?m).*^\s*(include\s+.*\.ini|repeat\s*=\s*[0-9]+|.*\$\{.*\})")
        configuration_class_regex = re.compile(r"\s*configuration-class\s*=\s*(\w+)")
        simulation_configs = []
        working_directory = os.path.dirname(ini_path)
        inifile_contents = read_file(ini_path)
        num_runs_fast = None if num_runs_fast_regex.search(inifile_contents) else 1
        ini_file = os.path.basename(ini_path)
        file = open(ini_path, encoding="utf-8")
        config_dicts = {"General": create_config_dict("General")}
        config_dict = {}
        for line in file:
            match = re.match(r"\[(Config +)?(.*?)\]", line)
            if match:
                config = match.group(2) or match.group(3)
                config_dict = create_config_dict(config)
                config_dicts[config] = config_dict
            match = re.match(r"#? *abstract *= *(\w+)", line)
            if match:
                config_dict["abstract"] = bool(match.group(1))
            match = re.match(r"#? *emulation *= *(\w+)", line)
            if match:
                config_dict["emulation"] = bool(match.group(1))
            match = re.match(r"#? *expected-result *= *\"(\w+)\"", line)
            if match:
                config_dict["expected_result"] = match.group(1)
            line = re.sub(r"(.*)#.*", "//1", line).strip()
            match = re.match(r" *extends *= *(\w+)", line)
            if match:
                config_dict["extends"] = match.group(1)
            match = re.match(r" *user-interface *= \"*(\w+)\"", line)
            if match:
                config_dict["user_interface"] = match.group(1)
            match = re.match(r"description *= *\"(.*)\"", line)
            if match:
                config_dict["description"] = match.group(1)
            match = re.match(r"network *= *(.*)", line)
            if match:
                config_dict["network"] = match.group(1)
            match = re.match(r"sim-time-limit *= *(.*)", line)
            if match:
                config_dict["sim_time_limit"] = match.group(1)
        general_config_dict = config_dicts["General"]
        for config, config_dict in config_dicts.items():
            config = config_dict["config"]
            if num_runs_fast:
                num_runs = num_runs_fast
            else:
                try:
                    inifile_contents = InifileContents(ini_path)
                    num_runs = inifile_contents.getNumRunsInConfig(config)
                except Exception as e:
                    if configuration_class_regex.search(inifile_contents):
                        self.build(mode="release")
                        executable = self.get_executable(mode="release")
                        if not os.path.exists(executable):
                            executable = self.get_executable(mode="release")
                        default_args = self.get_default_args()
                        args = [executable, *default_args, "-s", "-f", ini_file, "-c", config, "-q", "numruns"]
                    else:
                        executable = self.get_omnetpp_project().get_executable(mode="release")
                        args = [executable, "-s", "-f", ini_file, "-c", config, "-q", "numruns"]
                    result = run_command_with_logging(args, cwd=working_directory, env=self.get_env())
                    if result.returncode == 0:
                        # KLUDGE: this was added to test source dependency based task result caching
                        result.stdout = re.sub(r"INI dependency: (.*)", "", result.stdout)
                        num_runs = int(result.stdout)
                    else:
                        _logger.warn("Cannot determine number of runs: " + result.stderr + " in " + working_directory)
                        continue
            sim_time_limit = get_sim_time_limit(config_dicts, config)
            description = config_dict["description"]
            description_abstract = (re.search(r"\((a|A)bstract\)", description) is not None) if description else False
            abstract = (config_dict["network"] is None and config_dict["config"] == "General") or config_dict["abstract"] or description_abstract
            emulation = config_dict["emulation"]
            expected_result = config_dict["expected_result"]
            user_interface = config_dict["user_interface"] or general_config_dict["user_interface"]
            simulation_config = SimulationConfig(self, os.path.relpath(working_directory, self.get_full_path(".")), ini_file=ini_file, config=config, sim_time_limit=sim_time_limit, num_runs=num_runs, abstract=abstract, emulation=emulation, expected_result=expected_result, user_interface=user_interface, description=description)
            simulation_configs.append(simulation_config)
        return simulation_configs

    def collect_all_simulation_configs(self, ini_path_globs, concurrent=True, **kwargs):
        def local_collect_ini_file_simulation_configs(ini_path, **kwargs):
            return self.collect_ini_file_simulation_configs(ini_path, **kwargs)
        _logger.info(f"Collecting {self.name} simulation configs started")
        ini_paths = [f for f in itertools.chain.from_iterable(map(lambda g: glob.glob(g, recursive=True), ini_path_globs)) if os.path.isfile(f)]
        if concurrent:
            pool = multiprocessing.pool.ThreadPool(multiprocessing.cpu_count())
            result = list(itertools.chain.from_iterable(pool.map(local_collect_ini_file_simulation_configs, ini_paths)))
        else:
            result = list(itertools.chain.from_iterable(map(local_collect_ini_file_simulation_configs, ini_paths)))
        result.sort(key=lambda element: (element.working_directory, element.ini_file, element.config))
        _logger.info(f"Collecting {self.name} simulation configs ended")
        return result

    def get_all_simulation_configs(self, **kwargs):
        ini_path_globs = list(map(lambda ini_file_folder: self.get_full_path(os.path.join(ini_file_folder, "**/*.ini")), self.ini_file_folders))
        return self.collect_all_simulation_configs(ini_path_globs, **kwargs)

    def get_simulation_configs(self, **kwargs):
        if self.simulation_configs is None:
            self.ensure_mounted()
            self.simulation_configs = self.get_all_simulation_configs()
        return list(builtins.filter(lambda simulation_config: simulation_config.matches_filter(**kwargs), self.simulation_configs))

    def get_binary_simulation_distribution_file_paths(self):
        if self.binary_simulation_distribution_file_paths is None:
            self.binary_simulation_distribution_file_paths = self.collect_binary_simulation_distribution_file_paths()
        return self.binary_simulation_distribution_file_paths

from opp_repl.simulation.workspace import *  # noqa: F401,F403 — re-export workspace API

# -- Git worktree helpers -------------------------------------------------

def make_worktree_simulation_project(simulation_project, git_hash):
    """Create a git worktree at *git_hash* and return a new :py:class:`SimulationProject` for it.

    The worktree is placed next to the original project folder, named
    ``<basename>-<short_hash>``.  If the worktree already exists, it is
    reused.

    Parameters:
        simulation_project (:py:class:`SimulationProject`):
            The source project whose repository is checked out.
        git_hash (str):
            A git commit-ish (hash, tag, branch name, etc.).

    Returns:
        :py:class:`SimulationProject`: A new project rooted at the worktree.
    """
    src_root = simulation_project.get_root_path()
    if src_root is None:
        raise RuntimeError("Source project has no root path")
    short_hash = git_hash[:10]
    worktree_path = os.path.join(os.path.dirname(src_root),
                                 os.path.basename(src_root) + "-" + short_hash)
    if not os.path.isdir(worktree_path):
        subprocess.run(
            ["git", "worktree", "add", worktree_path, git_hash],
            cwd=src_root, check=True,
        )
    import copy
    project = copy.copy(simulation_project)
    project.name = simulation_project.name + "-" + short_hash
    project.root_folder = worktree_path
    project.simulation_configs = None
    project._overlay = None
    return project

