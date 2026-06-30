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
import shlex
import shutil
import socket
import subprocess
import textwrap

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

    Optionally supports overlay builds via fuse-overlayfs.  When *overlay_name*
    is given, an :py:class:`OverlayMount` is created and all paths resolve to
    the overlay's merged directory instead of the original source tree.
    """

    def __init__(self, name=None, version=None, root_folder_environment_variable="__omnetpp_root_dir", root_folder=None,
                 overlay_name=None, overlay_build_root=None, opp_env_workspace=None, opp_env_project=None):
        """
        Initializes a new OMNeT++ project.

        Parameters:
            name (string or None):
                The human-readable name of the OMNeT++ project.  When the
                project is registered via :py:func:`define_omnetpp_project`
                or loaded from a ``.opp`` file, the workspace overrides this
                with the registration name.

            version (string or None):
                The version string.

            root_folder_environment_variable (string):
                The operating system environment variable specifying the root folder of the OMNeT++ installation.

            root_folder (string or None):
                The root folder of the OMNeT++ installation. If specified, it is used instead of the environment variable.

            overlay_name (str or None):
                If set, enables overlay mode.  An :py:class:`OverlayMount` is
                created with this name and all paths resolve to the overlay's
                merged directory.

            overlay_build_root (str or None):
                Override for the overlay build root directory.
        """
        self.name = name
        self.version = version
        self.root_folder_environment_variable = root_folder_environment_variable
        self.root_folder = root_folder
        self.opp_env_workspace = opp_env_workspace
        self.opp_env_project = opp_env_project
        self._overlay = None
        if overlay_name is not None:
            from opp_repl.simulation.overlay import OverlayMount
            self._overlay = OverlayMount(self.get_root_path(), overlay_name, overlay_build_root)
            self.root_folder = self._overlay.merged_path

    def __repr__(self):
        overlay = f", overlay={self._overlay.overlay_name!r}" if self._overlay else ""
        return f"OmnetppProject(root_folder_environment_variable={self.root_folder_environment_variable!r}, root_folder={self.root_folder!r}{overlay})"

    def has_root_path(self):
        """True if the project root can be resolved without raising."""
        if self.root_folder is not None:
            return True
        if self.root_folder_environment_variable is not None and self.root_folder_environment_variable in os.environ:
            return True
        return False

    def get_root_path(self):
        """Return the absolute project root. Raises RuntimeError when neither
        ``root_folder`` is set nor the named env var resolves — every operation
        that actually needs the project on disk (build, clean, run, list files)
        depends on this, so failing loud here gives a self-explanatory error
        instead of an opaque ``NoneType`` crash deeper in stdlib."""
        if self.root_folder is not None:
            return os.path.abspath(self.root_folder)
        if self.root_folder_environment_variable is not None and self.root_folder_environment_variable in os.environ:
            return os.path.abspath(os.environ[self.root_folder_environment_variable])
        env = self.root_folder_environment_variable
        hint = (f"set the '{env}' environment variable" if env
                else "pass root_folder=... when defining the project")
        raise RuntimeError(
            f"Cannot resolve root path of OMNeT++ project '{self.name}': "
            f"project root is not set ({hint}).")

    def get_full_path(self, path):
        return os.path.abspath(os.path.join(self.get_root_path(), path))

    def get_relative_path(self, path):
        return os.path.relpath(path, self.get_root_path())

    def get_library_suffix(self, mode="release"):
        """Return the binary suffix for *mode* (``"_release"``, ``"_dbg"``,
        ``"_sanitize"``, ``"_coverage"``, ``"_profile"``). See the
        :doc:`Building </building>` guide for what each mode produces."""
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
        suffix = self.get_library_suffix(mode=mode)
        return os.path.abspath(os.path.join(self.get_root_path(), "bin/opp_run" + suffix))

    def ensure_configured(self, **kwargs):
        """Run ``./configure`` as a task if ``Makefile.inc`` does not yet exist.

        A fresh git worktree will not contain the generated ``Makefile.inc``.
        If ``configure.user`` is also missing, it is copied from the original
        source tree (falling back to ``configure.user.dist``).
        """
        from opp_repl.simulation.build_omnetpp import ConfigureOmnetppTask
        return ConfigureOmnetppTask(omnetpp_project=self).run(**kwargs)

    def get_env(self):
        env = os.environ.copy()
        if not self.has_root_path():
            return env
        root = self.get_root_path()
        bin_dir = os.path.join(root, "bin")
        lib_dir = os.path.join(root, "lib")
        if bin_dir not in env.get("PATH", "").split(os.pathsep):
            env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        if lib_dir not in env.get("LD_LIBRARY_PATH", "").split(os.pathsep):
            env["LD_LIBRARY_PATH"] = lib_dir + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        # CCACHE_BASEDIR: make paths relative so builds in different worktrees can share the cache
        env.setdefault("CCACHE_BASEDIR", root)
        # CCACHE_NOHASHDIR: don't hash the CWD so worktrees at different absolute paths still hit the cache
        env.setdefault("CCACHE_NOHASHDIR", "true")
        # CCACHE_SLOPPINESS: tolerate trivial cache-busters so makefile/task engines share entries
        env.setdefault("CCACHE_SLOPPINESS",
                       "time_macros,locale,include_file_mtime,include_file_ctime,system_headers,pch_defines")
        # CCACHE_COMPILERCHECK=content: hash the compiler binary by content rather than mtime/size
        env.setdefault("CCACHE_COMPILERCHECK", "content")
        return env

    def is_build_up_to_date(self, mode="release"):
        if not self.has_root_path():
            return False
        root = self.get_root_path()
        if not os.path.isfile(os.path.join(root, "Makefile")):
            return False
        env = self.get_env()
        args = ["make", "-q", "MODE=" + mode]
        if self.opp_env_workspace:
            opp_env_project = self.opp_env_project or self.name
            shell_cmd = "cd " + shlex.quote(root) + " && " + shlex.join(args)
            args = ["opp_env", "-l", "WARN", "run", opp_env_project, "-w", self.opp_env_workspace, "-c", shell_cmd]
            result = subprocess.run(args, capture_output=True)
        else:
            result = subprocess.run(args, cwd=root, env=env, capture_output=True)
        return result.returncode == 0

    def build(self, mode="release", build_engine=None, **kwargs):
        """
        Build OMNeT++.

        Parameters:
            mode (str): build mode — one of ``"release"``, ``"debug"``,
                ``"sanitize"``, ``"coverage"``, ``"profile"``. See the
                :doc:`Building </building>` guide for details.
            build_engine (str): build engine — ``"makefile"`` to run ``make``,
                or ``"task"`` to drive the build via per-file
                :py:mod:`opp_repl <opp_repl>` tasks. If unspecified, the global
                default from :py:func:`get_default_build_engine` is used.
                Orthogonal to ``mode``.

        See :py:func:`build_omnetpp <opp_repl.simulation.build_omnetpp.build_omnetpp>`.
        """
        from opp_repl.simulation.build_omnetpp import build_omnetpp
        return build_omnetpp(omnetpp_project=self, mode=mode, build_engine=build_engine, **kwargs)

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

    def get_makefile_inc_config(self, mode="release"):
        """
        Returns a :py:class:`MakefileIncConfig <opp_repl.simulation.makefile_vars.MakefileIncConfig>`
        with the evaluated Makefile.inc variables for the given build mode.

        Results are cached per mode.
        """
        if not hasattr(self, "_makefile_inc_configs"):
            self._makefile_inc_configs = {}
        if mode not in self._makefile_inc_configs:
            from opp_repl.simulation.makefile_vars import MakefileIncConfig
            self._makefile_inc_configs[mode] = MakefileIncConfig(self.get_root_path(), mode)
        return self._makefile_inc_configs[mode]

    def clean(self, mode="release", build_engine=None, **kwargs):
        """
        Clean OMNeT++.

        Parameters:
            mode (str): build mode to clean — one of ``"release"``, ``"debug"``,
                ``"sanitize"``, ``"coverage"``, ``"profile"``. See the
                :doc:`Building </building>` guide for details.
            build_engine (str): build engine — ``"makefile"`` to run ``make clean``,
                or ``"task"`` to remove generated sources/build artifacts
                directly. If unspecified, the global default from
                :py:func:`get_default_build_engine` is used.
                See :py:func:`clean_omnetpp <opp_repl.simulation.build_omnetpp.clean_omnetpp>`.
        """
        if self._overlay is not None:
            self._overlay.clean()
            return
        from opp_repl.simulation.build_omnetpp import clean_omnetpp
        return clean_omnetpp(omnetpp_project=self, mode=mode, build_engine=build_engine, **kwargs)

# Aspects a project may declare per test kind in its `.opp` `test_parameters`.
# Each is optional and only the kinds that need it declare it (kinds are
# heterogeneous: some have a result store, some a baseline repo, some a runner).
#   defaults  — kwargs merged into run_<kind>_tests as if the caller passed them
#   store     — expected-values file in the project tree (fingerprint/speed JSON)
#   baseline  — external repo to check out before the kind runs: {repository, ref, folder}
#   runner    — dotted "module:function" ref for a project-specific kind (validation)
RECOGNISED_TEST_ASPECTS = frozenset({"defaults", "store", "baseline", "runner"})


def _validate_test_parameters(test_parameters, project_name):
    for kind, params in test_parameters.items():
        if not isinstance(params, dict):
            raise ValueError(f"test_parameters[{kind!r}] for project {project_name!r} must be a dict, "
                             f"got {type(params).__name__}")
        unknown = set(params) - RECOGNISED_TEST_ASPECTS
        if unknown:
            raise ValueError(f"test_parameters[{kind!r}] for project {project_name!r} has unknown "
                             f"aspect(s) {sorted(unknown)}; recognised: {sorted(RECOGNISED_TEST_ASPECTS)}")


def apply_project_test_defaults(kind, kwargs):
    """Merge a project's per-kind ``defaults`` (declared in its ``.opp``
    ``test_parameters``) into *kwargs* as if the caller had passed them; explicit
    kwargs win. Resolves and pins ``simulation_project`` so downstream code does
    not re-resolve it. Called at the top of each ``run_<kind>_tests``."""
    simulation_project = kwargs.get("simulation_project") or get_default_simulation_project()
    kwargs = {**kwargs, "simulation_project": simulation_project}
    defaults = simulation_project.test_parameters.get(kind, {}).get("defaults", {})
    return {**defaults, **kwargs}


class SimulationProject:
    """
    Represents a simulation project that usually comes with its own modules and their C++ implementation, and also with
    several example simulations.

    Please note that undocumented features are not supposed to be called by the user.
    """

    def __init__(self, name, version=None, git_hash=None, git_diff_hash=None, root_folder_environment_variable=None, root_folder=None, root_folder_environment_variable_relative_folder=".", omnetpp_project=None,
                 bin_folder=".", library_folder=".", executables=None, dynamic_libraries=None, static_libraries=None, build_types=["dynamic library"],
                 ned_folders=["."], ned_exclusions=[], ini_file_folders=["."], python_folders=["python"], image_folders=["."],
                 include_folders=["."], cpp_folders=["."], cpp_exclusions=[], cpp_defines=[], msg_folders=["."],
                 media_folder=".", module_image_baseline_folder="media/module_images", statistics_folder=".", fingerprint_store="fingerprint.json", speed_store="speed.json", dependency_store="dependency.json",
                 validation_test_runner=None, test_parameters=None,
                 used_projects=[], external_bin_folders=[], external_library_folders=[], external_libraries=[], external_include_folders=[],
                 dll_symbol=None, feature_libraries=None, pkg_config_libraries=None, opp_defines_file=None, precompiled_header=None, extra_cflags=[], extra_ldflags=[],
                 simulation_configs=None, overlay_name=None, overlay_build_root=None, opp_env_workspace=None, opp_env_project=None,
                 github_owner=None, github_repository=None, github_workflows=None, workspace=None, **kwargs):
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

            root_folder_environment_variable (string):
                The operating system environment variable specifying the root folder.

            root_folder (string or None):
                The root folder of the simulation project. If specified, it is used instead of the root_folder_environment_variable environment variable.

            omnetpp_project (:py:class:`OmnetppProject` or None):
                The OMNeT++ project representing the OMNeT++ installation to use.
                If unspecified, defaults to the global ``default_omnetpp_project``
                when an executable is needed (e.g. for running simulations).

            root_folder_environment_variable_relative_folder (string):
                The directory of the simulation project relative to the value of the root_folder_environment_variable environment variable.

            bin_folder (string):
                The directory of the binary output files relative to the root folder.

            library_folder (string):
                The directory of the library output files relative to the root folder.

            executables (List of strings):
                The list of executables that are built.

            dynamic_libraries (List of strings):
                The list of dynamic libraries that are built.

            static_libraries (List of strings):
                TODO

            build_types (List of strings):
                The list of build output types. Valid values are "executable", "dynamic library", "static library".

            ned_folders (List of strings):
                The list of root folder relative directories for NED files.

            ned_exclusions (List of strings):
                The list of excluded NED packages.

            ini_file_folders (List of strings):
                The list of root folder relative directories for INI files.

            python_folders (List of strings):
                The list of root folder relative directories for Python source files.

            image_folders (List of strings):
                The list of root folder relative directories for image files.

            include_folders (List of strings):
                The list of root folder relative directories for C++ include files.

            cpp_folders (List of strings):
                The list of root folder relative directories for C++ source files.

            cpp_exclusions (List of strings):
                Directories (relative to each ``cpp_folders`` / ``msg_folders``
                entry) whose ``.cc`` / ``.h`` / ``.msg`` files should be skipped.
                Mirrors ``opp_makemake -X<dir>`` — use this when the makefile build
                excludes a feature subtree (e.g. ``inet/applications/voipstream``)
                so the task-engine globber agrees with what ``make`` actually builds.

            cpp_defines (List of strings):
                The list of C++ macro definitions that are passed to the C++ compiler.

            msg_folders (List of strings):
                The list of root folder relative directories for MSG files.

            media_folder (String):
                The relative path of chart image files for chart tests.

            module_image_baseline_folder (String):
                The relative path of the baseline module-image folder
                for module-image tests (default ``"media/module_images"``).
                See :doc:`Module-image tests </module_image_tests>`.

            statistics_folder (String):
                The relative path of scalar statistic result files for statistical tests.

            fingerprint_store (String):
                The relative path of the JSON fingerprint store for fingerprint tests.

            speed_store (String):
                The relative path of the JSON measurement store for speed tests.

            dependency_store (String):
                The relative path of the JSON dependency store for simulation task dependencies.

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

            overlay_name (str or None):
                If set, enables overlay mode.  An :py:class:`OverlayMount` is
                created with this name and all paths resolve to the overlay's
                merged directory.

            overlay_build_root (str or None):
                Override for the overlay build root directory.

            opp_env_workspace (str or None):
                If set, simulations are run inside an opp_env environment.
                The value is the path to the opp_env workspace directory.

            opp_env_project (str or None):
                The opp_env project identifier (e.g. ``"inet-4.6.0"``).
                Defaults to the project name if not specified.

            github_owner (str or None):
                GitHub owner or organization (e.g. ``"inet-framework"``).
                Used by :py:func:`dispatch_workflow <opp_repl.common.github.dispatch_workflow>`.

            github_repository (str or None):
                GitHub repository name (e.g. ``"inet"``).
                Used by :py:func:`dispatch_workflow <opp_repl.common.github.dispatch_workflow>`.

            dll_symbol (str or None):
                The DLL export/import symbol for the project (e.g. ``"INET"``).
                When set, ``-D<symbol>_EXPORT`` is passed to the C++ compiler
                and ``-P<symbol>_API`` is passed to the message compiler.

            feature_libraries (dict or None):
                Maps feature IDs to their library requirements. Libraries are
                only resolved and linked when the feature is enabled. Each value
                is a dict with one or more of:

                - ``"pkg_config"``: list of pkg-config package names.
                  Resolved via ``pkg-config --cflags`` / ``--libs``.
                - ``"defines"``: list of preprocessor defines (without ``-D``)
                  added to cflags when pkg-config detection succeeds.
                - ``"makefile_inc_libs"``: Makefile.inc variable name whose
                  value is added to ldflags (e.g. ``"OSG_LIBS"``).
                - ``"makefile_inc_flags"``: Makefile.inc variable name whose
                  value is added to both cflags and ldflags (e.g.
                  ``"OPENMP_FLAGS"``).

                Example::

                    feature_libraries={
                        "VoipStream": {"pkg_config": ["libavcodec", "libavformat", "libavutil", "libswresample"]},
                        "Z3GateSchedulingConfigurator": {"pkg_config": ["z3"]},
                        "VisualizationOsg": {"makefile_inc_libs": "OSG_LIBS"},
                        "OpenMP": {"makefile_inc_flags": "OPENMP_FLAGS"},
                    }

            precompiled_header (str or None):
                Relative path to the precompiled header file template.
                May contain ``{mode}`` placeholder (e.g.
                ``"inet/common/precompiled_{mode}.h"``).

            extra_cflags (list of str):
                Additional compiler flags (e.g. ``["-Wno-overloaded-virtual"]``).

            extra_ldflags (list of str):
                Additional linker flags.

            github_workflows (list of str or None):
                List of GitHub Actions workflow file names
                (e.g. ``["fingerprint-tests.yml"]``).  Used by
                :py:func:`dispatch_all_workflows <opp_repl.common.github.dispatch_all_workflows>`.

            workspace (:py:class:`SimulationWorkspace` or None):
                The workspace this project belongs to.  Used for resolving
                ``used_projects`` references and the associated OMNeT++
                project.  If ``None``, the project falls back to the default
                workspace at access time (see :py:meth:`get_workspace`).
                Normally set automatically by
                :py:meth:`SimulationWorkspace.define_simulation_project`.

            kwargs (dict):
                Ignored.
        """
        self.name = name
        self.version = version
        self.root_folder_environment_variable = root_folder_environment_variable
        self.root_folder = root_folder
        self.root_folder_environment_variable_relative_folder = root_folder_environment_variable_relative_folder
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
        self.cpp_exclusions = cpp_exclusions
        self.cpp_defines = cpp_defines
        self.msg_folders = msg_folders
        # Per-kind test configuration declared in the project's `.opp`. A single
        # untyped dict keyed by test kind; see RECOGNISED_TEST_ASPECTS. A `store`
        # aspect (an in-tree expected-values file) derives the legacy store attrs
        # below, so existing call sites (self.fingerprint_store, …) keep working.
        #
        # NOTE: media_folder / statistics_folder are the *in-tree read paths* the
        # chart/statistical tests use, and are NOT the same as a baseline's
        # checkout `folder` (where opp_ci clones the external baseline repo).
        # They coincide for statistical (`statistics`) but differ for chart
        # (clone → `media`, read via the committed `doc/media` symlinks), so they
        # stay independent project params — do not derive them from baseline.folder.
        test_parameters = test_parameters or {}
        _validate_test_parameters(test_parameters, name)
        self.test_parameters = test_parameters
        self.module_image_baseline_folder = module_image_baseline_folder
        self.dependency_store = dependency_store
        self.media_folder = media_folder
        self.statistics_folder = statistics_folder
        self.fingerprint_store = test_parameters.get("fingerprint", {}).get("store", fingerprint_store)
        self.speed_store = test_parameters.get("speed", {}).get("store", speed_store)
        # Dotted "module.path:function" reference to the project-specific
        # validation-test runner (validation tests compare results against
        # analytical models, so they live in the project, not opp_repl). The
        # generic opp_repl.test.validation.run_validation_tests resolves it.
        self.validation_test_runner = test_parameters.get("validation", {}).get("runner", validation_test_runner)
        self.used_projects = used_projects
        self.external_bin_folders = external_bin_folders
        self.external_library_folders = external_library_folders
        self.external_libraries = external_libraries
        self.external_include_folders = external_include_folders
        self.simulation_configs = simulation_configs
        self.opp_env_workspace = opp_env_workspace
        self.opp_env_project = opp_env_project or name
        self.dll_symbol = dll_symbol
        self.feature_libraries = feature_libraries or {}
        self.pkg_config_libraries = pkg_config_libraries  # deprecated, use feature_libraries
        self.opp_defines_file = opp_defines_file
        self.precompiled_header = precompiled_header
        self.extra_cflags = extra_cflags
        self.extra_ldflags = extra_ldflags
        self.github_owner = github_owner
        self.github_repository = github_repository
        self.github_workflows = github_workflows
        self._simulation_configs_freshness_key = None
        self.binary_simulation_distribution_file_paths = None
        self._overlay = None
        self.workspace = workspace
        if overlay_name is not None:
            from opp_repl.simulation.overlay import OverlayMount
            self._overlay = OverlayMount(self.get_root_path(), overlay_name, overlay_build_root)
            self.root_folder = self._overlay.merged_path
            self.simulation_configs = None

    def __repr__(self):
        return repr(self, ["name", "version", "git_hash", "git_diff_hash"])

    def get_name(self):
        return self.name

    def get_test_baseline(self, kind):
        """Return the ``{repository, ref, folder}`` baseline-repo declaration for a
        test kind (chart/statistical compare against an external baseline repo that
        must be checked out before the run), or ``None`` if the kind declares none."""
        return self.test_parameters.get(kind, {}).get("baseline")

    def get_workspace(self):
        """Return the workspace this project belongs to, or the default workspace."""
        return self.workspace or get_default_simulation_workspace()

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
        if opp is not None and opp.has_root_path():
            opp_root = opp.get_root_path()
            bin_dir = os.path.join(opp_root, "bin")
            lib_dir = os.path.join(opp_root, "lib")
            if bin_dir not in env.get("PATH", "").split(os.pathsep):
                env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
            if lib_dir not in env.get("LD_LIBRARY_PATH", "").split(os.pathsep):
                env["LD_LIBRARY_PATH"] = lib_dir + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        if self.has_root_path():
            root = self.get_root_path()
            # CCACHE_BASEDIR: make paths relative so builds in different worktrees can share the cache
            env.setdefault("CCACHE_BASEDIR", root)
            # CCACHE_NOHASHDIR: don't hash the CWD so worktrees at different absolute paths still hit the cache
            env.setdefault("CCACHE_NOHASHDIR", "true")
            # CCACHE_SLOPPINESS: tolerate trivial cache-busters so makefile/task engines share entries
            env.setdefault("CCACHE_SLOPPINESS",
                           "time_macros,locale,include_file_mtime,include_file_ctime,system_headers,pch_defines")
            # CCACHE_COMPILERCHECK=content: hash the compiler binary by content rather than mtime/size
            env.setdefault("CCACHE_COMPILERCHECK", "content")
        ws = self.get_workspace()
        for used_project_name in self.used_projects:
            used_project = ws.get_simulation_project(used_project_name, None)
            if used_project is None or not used_project.has_root_path():
                continue
            env_var = used_project.root_folder_environment_variable or (used_project_name.upper().replace("-", "_") + "_ROOT")
            env[env_var] = used_project.get_root_path()
            used_lib_dir = used_project.get_library_folder_full_path()
            if used_lib_dir and used_lib_dir not in env.get("LD_LIBRARY_PATH", "").split(os.pathsep):
                env["LD_LIBRARY_PATH"] = used_lib_dir + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        return env

    def get_environment_variable_relative_path(self, enviroment_variable, path):
        return os.path.abspath(os.path.join(os.environ[enviroment_variable], path)) if enviroment_variable in os.environ else None

    def has_root_path(self):
        """True if the project root can be resolved without raising."""
        if self.root_folder is not None:
            return True
        if self.root_folder_environment_variable is not None and self.root_folder_environment_variable in os.environ:
            return True
        return False

    def get_root_path(self):
        """Return the absolute project root. Raises RuntimeError when neither
        ``root_folder`` is set nor the named env var resolves — every operation
        that actually needs the project on disk (build, clean, run, list files)
        depends on this, so failing loud here gives a self-explanatory error
        instead of an opaque ``NoneType`` crash deeper in stdlib."""
        if self.root_folder is not None:
            return os.path.abspath(self.root_folder)
        if self.root_folder_environment_variable is not None and self.root_folder_environment_variable in os.environ:
            return os.path.abspath(os.environ[self.root_folder_environment_variable])
        env = self.root_folder_environment_variable
        hint = (f"set the '{env}' environment variable" if env
                else "pass root_folder=... when defining the project")
        raise RuntimeError(
            f"Cannot resolve root path of simulation project '{self.name}': "
            f"project root is not set ({hint}).")

    def get_full_path(self, path):
        base = os.path.join(self.get_root_path(), self.root_folder_environment_variable_relative_folder)
        return os.path.abspath(os.path.join(base, path))

    def get_relative_path(self, path):
        base = os.path.join(self.get_root_path(), self.root_folder_environment_variable_relative_folder)
        return os.path.relpath(path, base)

    def get_omnetpp_project(self):
        if isinstance(self.omnetpp_project, str):
            ws = self.get_workspace()
            try:
                self.omnetpp_project = ws.get_omnetpp_project(self.omnetpp_project)
            except KeyError:
                root = os.environ.get("__omnetpp_root_dir")
                if root:
                    self.omnetpp_project = ws.define_omnetpp_project(self.omnetpp_project, root_folder=root)
                else:
                    self.omnetpp_project = None
        ws = self.get_workspace()
        result = self.omnetpp_project or ws.get_default_omnetpp_project()
        if result is None:
            omnetpp_projects = ws.get_omnetpp_projects()
            if ("omnetpp", None) in omnetpp_projects:
                result = omnetpp_projects[("omnetpp", None)]
        return result

    def get_executable(self, mode="release"):
        dynamic_loading = self.build_types[0] == "dynamic library"
        if dynamic_loading:
            return self.get_omnetpp_project().get_executable(mode=mode)
        else:
            suffix = "" if mode == "release" else self.get_omnetpp_project().get_library_suffix(mode=mode)
            executable = os.path.join(self.root_folder_environment_variable_relative_folder, self.executables[0] + suffix)
            return os.path.abspath(os.path.join(self.get_root_path(), executable))

    def get_library_folder_full_path(self):
        return self.get_full_path(self.library_folder)

    def get_dynamic_libraries_for_running(self):
        result = []
        if self.build_types[0] == "dynamic library":
            for library in self.dynamic_libraries:
                result.append(os.path.join(self.library_folder, library))
            ws = self.get_workspace()
            for used_project in self.used_projects:
                simulation_project = ws.get_simulation_project(used_project, None)
                result = result + list(map(simulation_project.get_full_path, simulation_project.get_dynamic_libraries_for_running()))
        return result

    def get_ned_folders_for_running(self):
        result = self.ned_folders
        ws = self.get_workspace()
        for used_project in self.used_projects:
            simulation_project = ws.get_simulation_project(used_project, None)
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
        ws = self.get_workspace()
        return self.get_direct_include_folders() + flatten(map(lambda used_project: ws.get_simulation_project(used_project, None).get_direct_include_folders(), self.used_projects))

    def get_direct_msg_folders(self):
        return list(map(lambda msg_folder: self.get_full_path(msg_folder), self.msg_folders))

    def get_effective_msg_folders(self):
        ws = self.get_workspace()
        return self.get_direct_msg_folders() + flatten(map(lambda used_project: ws.get_simulation_project(used_project, None).get_direct_msg_folders(), self.used_projects))

    def _is_excluded_by_cpp_exclusions(self, file_path, source_folder):
        """
        True if ``file_path`` (relative to project root) lies under any of
        ``self.cpp_exclusions`` (each given relative to ``source_folder``).
        Mirrors ``opp_makemake -X<dir>``.
        """
        if not self.cpp_exclusions:
            return False
        rel = os.path.relpath(file_path, source_folder)
        for excl in self.cpp_exclusions:
            if rel == excl or rel.startswith(excl.rstrip("/") + "/"):
                return True
        return False

    def get_cpp_files(self):
        cpp_files = []
        for cpp_folder in self.cpp_folders:
            file_paths = list(filter(lambda file_path: not re.search(r"_m\.cc", file_path), glob.glob(self.get_full_path(os.path.join(cpp_folder, "**/*.cc")), recursive=True)))
            for file_path in file_paths:
                rel = self.get_relative_path(file_path)
                if self._is_excluded_by_cpp_exclusions(rel, cpp_folder):
                    continue
                cpp_files.append(rel)
        return cpp_files

    def get_header_files(self):
        header_files = []
        for cpp_folder in self.cpp_folders:
            file_paths = list(filter(lambda file_path: not re.search(r"_m\.h", file_path), glob.glob(self.get_full_path(os.path.join(cpp_folder, "**/*.h")), recursive=True)))
            for file_path in file_paths:
                rel = self.get_relative_path(file_path)
                if self._is_excluded_by_cpp_exclusions(rel, cpp_folder):
                    continue
                header_files.append(rel)
        return header_files

    def get_msg_files(self):
        msg_files = []
        for msg_folder in self.msg_folders:
            file_paths = glob.glob(self.get_full_path(os.path.join(msg_folder, "**/*.msg")), recursive=True)
            for file_path in file_paths:
                rel = self.get_relative_path(file_path)
                if self._is_excluded_by_cpp_exclusions(rel, msg_folder):
                    continue
                msg_files.append(rel)
        return msg_files

    def build(self, mode="release", recursive=True, build_engine=None, **kwargs):
        self.ensure_mounted()
        if recursive:
            if self.used_projects:
                ws = self.get_workspace()
                for used_project_name in self.used_projects:
                    used_project = ws.get_simulation_project(used_project_name, None)
                    if used_project is not None:
                        used_project.build(mode=mode, recursive=recursive, build_engine=build_engine, **kwargs)
            else:
                opp = self.get_omnetpp_project()
                if opp is not None:
                    opp.build(mode=mode, build_engine=build_engine)
        import opp_repl.simulation.build
        return opp_repl.simulation.build.build_project(simulation_project=self, mode=mode, build_engine=build_engine, **kwargs)

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

    def clean(self, mode="release", recursive=True, build_engine=None, **kwargs):
        if recursive:
            if self.used_projects:
                ws = self.get_workspace()
                for used_project_name in self.used_projects:
                    used_project = ws.get_simulation_project(used_project_name, None)
                    if used_project is not None:
                        used_project.clean(mode=mode, recursive=recursive, build_engine=build_engine, **kwargs)
            else:
                opp = self.get_omnetpp_project()
                if opp is not None:
                    opp.clean(mode=mode, build_engine=build_engine)
        if self._overlay is not None:
            self._overlay.clean()
            return None
        import opp_repl.simulation.build
        return opp_repl.simulation.build.clean_project(simulation_project=self, mode=mode, build_engine=build_engine, **kwargs)

    def get_num_runs_in_config(self, ini_path, config, mode="release"):
        num_runs_fast_regex = re.compile(r"(?m).*^\s*(include\s+.*\.ini|repeat\s*=\s*[0-9]+|.*\$\{.*\})")
        inifile_text = read_file(ini_path)
        if not num_runs_fast_regex.search(inifile_text):
            return 1
        working_directory = os.path.dirname(ini_path)
        ini_file = os.path.basename(ini_path)
        configuration_class_regex = re.compile(r"\s*configuration-class\s*=\s*(\w+)")
        try:
            inifile_contents = InifileContents(ini_path)
            return inifile_contents.getNumRunsInConfig(config)
        except Exception as e:
            inifile_text = read_file(ini_path)
            if configuration_class_regex.search(inifile_text):
                if self.opp_env_workspace:
                    _logger.warn("Cannot determine number of runs for opp_env project with configuration-class in " + working_directory)
                    return None
                executable = self.get_executable(mode=mode)
                default_args = self.get_default_args()
                args = [executable, *default_args, "-s", "-f", ini_file, "-c", config, "-q", "numruns"]
            else:
                if self.opp_env_workspace:
                    omnetpp_project = self.get_omnetpp_project()
                    suffix = omnetpp_project.get_library_suffix(mode=mode) if omnetpp_project else "_release"
                    executable = shutil.which("opp_run" + suffix) or shutil.which("opp_run")
                else:
                    executable = self.get_omnetpp_project().get_executable(mode=mode)
                if executable is None or not os.path.exists(executable):
                    _logger.warn("Cannot determine number of runs: opp_run not found in " + working_directory)
                    return None
                default_args = self.get_default_args()
                args = [executable, *default_args, "-s", "-f", ini_file, "-c", config, "-q", "numruns"]
            result = run_command_with_logging(args, cwd=working_directory, command_line_logger=_logger)
            if result.returncode == 0:
                # KLUDGE: this was added to test source dependency based task result caching
                result.stdout = re.sub(r"INI dependency: (.*)", "", result.stdout)
                return int(result.stdout)
            else:
                _logger.warn("Cannot determine number of runs: " + result.stderr + " in " + working_directory)
                return None

    # KLUDGE TODO replace this with a Python binding to the C++ configuration reader
    def collect_ini_file_simulation_configs(self, ini_path, mode="release"):
        def get_inherited(config_dicts, config, key):
            config_dict = config_dicts[config]
            if key in config_dict:
                return config_dict[key]
            if "extends" in config_dict:
                for base_config in config_dict["extends"].split(","):
                    if base_config in config_dicts:
                        value = get_inherited(config_dicts, base_config, key)
                        if value is not None:
                            return value
            return config_dicts["General"].get(key)
        def create_config_dict(config):
            return {"config": config, "abstract": False, "emulation": False, "expected_result": "DONE", "user_interface": None, "description": None, "network": None}
        simulation_configs = []
        working_directory = os.path.dirname(ini_path)
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
            match = re.match(r"#? *bounded *= *(\w+)", line)
            if match:
                config_dict["bounded"] = match.group(1).lower() == "true"
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
            match = re.match(r"cpu-time-limit *= *(.*)", line)
            if match:
                config_dict["cpu_time_limit"] = match.group(1)
            match = re.match(r"real-time-limit *= *(.*)", line)
            if match:
                config_dict["real_time_limit"] = match.group(1)
        general_config_dict = config_dicts["General"]
        for config, config_dict in config_dicts.items():
            config = config_dict["config"]
            num_runs = self.get_num_runs_in_config(ini_path, config, mode=mode)
            if num_runs is None:
                continue
            sim_time_limit = get_inherited(config_dicts, config, "sim_time_limit")
            cpu_time_limit = get_inherited(config_dicts, config, "cpu_time_limit")
            real_time_limit = get_inherited(config_dicts, config, "real_time_limit")
            explicit_bounded = get_inherited(config_dicts, config, "bounded")
            if explicit_bounded is None:
                bounded = bool(sim_time_limit or cpu_time_limit or real_time_limit)
            else:
                bounded = explicit_bounded
            description = config_dict["description"]
            description_abstract = (re.search(r"\((a|A)bstract\)", description) is not None) if description else False
            abstract = (config_dict["network"] is None and config_dict["config"] == "General") or config_dict["abstract"] or description_abstract
            emulation = config_dict["emulation"]
            expected_result = config_dict["expected_result"]
            user_interface = config_dict["user_interface"] or general_config_dict["user_interface"]
            simulation_config = SimulationConfig(self, os.path.relpath(working_directory, self.get_full_path(".")), ini_file=ini_file, config=config, sim_time_limit=sim_time_limit, cpu_time_limit=cpu_time_limit, real_time_limit=real_time_limit, bounded=bounded, num_runs=num_runs, abstract=abstract, emulation=emulation, expected_result=expected_result, user_interface=user_interface, description=description)
            simulation_configs.append(simulation_config)
        return simulation_configs

    def collect_all_simulation_configs(self, ini_path_globs, concurrent=True, build=None, mode="release", build_engine=None, **kwargs):
        def local_collect_ini_file_simulation_configs(ini_path):
            return self.collect_ini_file_simulation_configs(ini_path, mode=mode)
        _logger.info(f"Collecting {self.name} simulation configs started")
        ini_paths = [f for f in itertools.chain.from_iterable(map(lambda g: glob.glob(g, recursive=True), ini_path_globs)) if os.path.isfile(f)]
        if build is None:
            build = get_default_build_argument()
        if build:
            self.build(mode=mode, build_engine=build_engine)
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

    def _compute_simulation_configs_freshness_key(self):
        ini_path_globs = [self.get_full_path(os.path.join(f, "**/*.ini")) for f in self.ini_file_folders]
        ini_paths = sorted(p for g in ini_path_globs for p in glob.glob(g, recursive=True) if os.path.isfile(p))
        mtimes = tuple(os.path.getmtime(p) for p in ini_paths)
        return (tuple(ini_paths), mtimes)

    def get_simulation_configs(self, **kwargs):
        freshness_key = self._compute_simulation_configs_freshness_key()
        if self.simulation_configs is None or freshness_key != self._simulation_configs_freshness_key:
            self.ensure_mounted()
            self.simulation_configs = self.get_all_simulation_configs(**kwargs)
            self._simulation_configs_freshness_key = freshness_key
        return list(builtins.filter(lambda simulation_config: simulation_config.matches_filter(**kwargs), self.simulation_configs))

    def get_binary_simulation_distribution_file_paths(self):
        if self.binary_simulation_distribution_file_paths is None:
            self.binary_simulation_distribution_file_paths = self.collect_binary_simulation_distribution_file_paths()
        return self.binary_simulation_distribution_file_paths

    def get_analysis_files(self, filter=".*", exclude_filter=None, full_match=False, **kwargs):
        def _is_anf_v2(filename):
            return 'version="2"' in open(filename, "rt").read()
        simulation_project_path = self.get_full_path(".")
        analysis_file_names = map(lambda path: os.path.relpath(path, simulation_project_path), glob.glob(simulation_project_path + "/**/*.anf", recursive = True))
        return builtins.filter(lambda analysis_file_name: _is_anf_v2(simulation_project_path + "/" + analysis_file_name) and matches_filter(analysis_file_name, filter, exclude_filter, full_match), analysis_file_names)

from opp_repl.simulation.workspace import *  # noqa: F401,F403 — re-export workspace API


# -- Git worktree helpers -------------------------------------------------

def _get_git_root(path, optional=False):
    """Return the absolute path of the git repository root containing *path*.

    If *optional* is true, return ``None`` when *path* is not inside a git
    repository (without logging git's stderr).
    """
    if optional:
        probe = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path, capture_output=True, text=True,
        )
        return os.path.abspath(probe.stdout.strip()) if probe.returncode == 0 else None
    result = run_command_with_logging(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path, error_message="Failed to determine git root",
        command_line_logger=_logger,
    )
    return os.path.abspath(result.stdout.strip())

def _make_git_worktree(git_root, git_hash):
    """Ensure a worktree of *git_root* at *git_hash* exists and return its path.

    The worktree is placed next to *git_root*, named
    ``<basename>-<short_hash>``.  If it already exists it is reused.
    """
    short_hash = git_hash[:10]
    worktree_path = os.path.join(os.path.dirname(git_root),
                                 os.path.basename(git_root) + "-" + short_hash)
    if not os.path.isdir(worktree_path):
        run_command_with_logging(
            ["git", "worktree", "prune"],
            cwd=git_root,
            command_line_logger=_logger,
        )
        run_command_with_logging(
            ["git", "worktree", "add", "--detach", "-q", worktree_path, git_hash],
            cwd=git_root, error_message="Failed to create git worktree",
            command_line_logger=_logger,
        )
    return worktree_path

def make_worktree_simulation_project(simulation_project, git_hash):
    """Create a git worktree at *git_hash* and return a new :py:class:`SimulationProject` for it.

    The worktree is placed next to the git repository root, named
    ``<basename>-<short_hash>``.  If the worktree already exists, it is
    reused.

    Sub-projects whose root folder is a subdirectory of the git repository
    (e.g. ``samples/histograms`` inside *omnetpp*) are handled automatically:
    the worktree is created at the repository level and the returned project
    points to the matching subdirectory within it.  If the project's
    :py:class:`OmnetppProject` lives in the same repository, it is similarly
    redirected to the worktree.

    The returned project is registered in the source project's workspace
    under key ``(name, git_hash)``, so repeated calls with the same hash
    return the cached project (preserving lazily-populated state such as
    ``simulation_configs``).  :py:func:`remove_worktree_simulation_project`
    unregisters it again.

    Parameters:
        simulation_project (:py:class:`SimulationProject`):
            The source project whose repository is checked out.
        git_hash (str):
            A git commit-ish (hash, tag, branch name, etc.).

    Returns:
        :py:class:`SimulationProject`: A new project rooted at the worktree.
    """
    src_root = os.path.abspath(simulation_project.get_root_path())

    workspace = simulation_project.get_workspace()
    cached = workspace.get_simulation_projects().get((simulation_project.name, git_hash))
    if cached is not None:
        return cached

    git_root = _get_git_root(src_root, optional=True)
    if git_root is None:
        raise RuntimeError(
            f"Cannot compare across commits: simulation project {simulation_project.name!r} "
            f"at {src_root} is not in a git repository. This operation requires the project "
            f"to be a git checkout."
        )
    worktree_path = _make_git_worktree(git_root, git_hash)

    import copy
    project = copy.copy(simulation_project)
    project.version = git_hash
    rel_path = os.path.relpath(src_root, git_root)
    project.root_folder = worktree_path if rel_path == "." else os.path.join(worktree_path, rel_path)
    project.simulation_configs = None
    project._overlay = None

    # If the OMNeT++ installation lives in the same git repo, redirect it
    # into the worktree so that builds use the matching OMNeT++ version.
    # OMNeT++ may be installed outside of git (release tarball, package),
    # in which case we skip the redirect.
    omnetpp_project = simulation_project.get_omnetpp_project()
    if omnetpp_project is not None and omnetpp_project.has_root_path():
        omnetpp_root = os.path.abspath(omnetpp_project.get_root_path())
        omnetpp_git_root = _get_git_root(omnetpp_root, optional=True)
        if omnetpp_git_root == git_root:
                omnetpp_project_copy = copy.copy(omnetpp_project)
                omnetpp_rel = os.path.relpath(omnetpp_root, git_root)
                omnetpp_project_copy.root_folder = worktree_path if omnetpp_rel == "." else os.path.join(worktree_path, omnetpp_rel)
                project.omnetpp_project = omnetpp_project_copy

    workspace.set_simulation_project(simulation_project.name, git_hash, project)
    return project

def remove_worktree_simulation_project(simulation_project):
    """Remove the git worktree backing *simulation_project*.

    Counterpart to :py:func:`make_worktree_simulation_project`.  The worktree
    is located by asking ``git rev-parse --show-toplevel`` from the project's
    root folder (so sub-directory projects are handled correctly) and removed
    via ``git worktree remove --force``.  If the path no longer exists, the
    worktree removal is skipped, but the project is still unregistered from
    its workspace.

    Parameters:
        simulation_project (:py:class:`SimulationProject`):
            A project returned by :py:func:`make_worktree_simulation_project`.
    """
    root = simulation_project.get_root_path()
    if root and os.path.isdir(root):
        result = run_command_with_logging(
            ["git", "rev-parse", "--show-toplevel"], cwd=root,
            error_message="Failed to locate worktree top",
            command_line_logger=_logger)
        worktree_top = os.path.abspath(result.stdout.strip())
        run_command_with_logging(
            ["git", "worktree", "remove", "--force", worktree_top],
            cwd=os.path.dirname(worktree_top),
            error_message=f"Failed to remove git worktree {worktree_top}",
            command_line_logger=_logger)
    workspace = simulation_project.get_workspace()
    workspace.get_simulation_projects().pop(
        (simulation_project.name, simulation_project.version), None)

def create_project(name, path=None, template="executable", namespace=False, omnetpp_project="omnetpp"):
    """
    Creates a new simulation project directory with boilerplate files.

    The generated files are sufficient to immediately build and run the project
    using :py:func:`build_project <opp_repl.simulation.build.build_project>` and
    :py:func:`run_simulations <opp_repl.simulation.task.run_simulations>` after
    adding NED network definitions and C++ simple module implementations.

    Parameters:
        name (string):
            The project name.  Used for the directory name, the ``.opp`` file,
            and the executable output name.

        path (string or None):
            The parent directory where the project folder will be created.
            If ``None``, defaults to the current working directory.

        template (string):
            The project template to use.  Currently only ``"executable"`` is
            supported, which creates a standalone simulation executable.

        namespace (bool):
            If ``True``, the generated ``package.ned`` will contain an
            ``@namespace(<name>)`` directive, and C++ code must wrap
            ``Define_Module()`` calls in a matching ``namespace <name> { ... }``
            block.  If ``False`` (the default), no namespace is used and
            both NED types and C++ class registrations live in the global
            namespace.  Mismatched namespaces cause *"Class not found"*
            errors at runtime.

        omnetpp_project (string):
            The name of the OMNeT++ project to reference in the ``.opp`` file.

    Returns (:py:class:`SimulationProject`):
        The newly created and registered simulation project.
    """
    from opp_repl.simulation.workspace import load_opp_file
    if path is None:
        path = os.getcwd()
    project_dir = os.path.join(path, name)
    if os.path.isdir(project_dir) and os.listdir(project_dir):
        raise Exception(f"Directory '{project_dir}' already exists and is not empty")
    os.makedirs(project_dir, exist_ok=True)
    _logger.info(f"Creating project '{name}' in {project_dir}")

    _write_project_file(project_dir, f"{name}.opp", textwrap.dedent(f"""\
        SimulationProject(
            name="{name}",
            root_folder=".",
            omnetpp_project="{omnetpp_project}",
            build_types=["executable"],
            ned_folders=["."],
            ini_file_folders=["."],
        )
    """))

    _write_project_file(project_dir, ".oppbuildspec", textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8" standalone="no"?>
        <buildspec version="4.0">
            <dir makemake-options="--deep --meta:recurse --meta:export-library --meta:use-exported-libs --meta:feature-cflags --meta:feature-ldflags" path="." type="makemake"/>
        </buildspec>
    """))

    _write_project_file(project_dir, ".nedfolders", ".\n")

    if namespace:
        _write_project_file(project_dir, "package.ned", f"@namespace({name});\n")
    else:
        _write_project_file(project_dir, "package.ned", "")

    _write_project_file(project_dir, "omnetpp.ini", textwrap.dedent("""\
        [General]
    """))

    opp_file = os.path.join(project_dir, f"{name}.opp")
    _logger.info(f"Creating project '{name}' done")
    return load_opp_file(os.path.abspath(opp_file))

def _write_project_file(directory, filename, content):
    filepath = os.path.join(directory, filename)
    if os.path.exists(filepath):
        _logger.debug(f"Skipping existing file {filepath}")
        return
    with open(filepath, "w") as f:
        f.write(content)
    _logger.debug(f"Created {filepath}")

