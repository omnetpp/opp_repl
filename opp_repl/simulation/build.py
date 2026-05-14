"""
This module provides functionality for building simulation projects.

The main function is :py:func:`build_project`.
"""

import logging
import multiprocessing
import os
import shlex
import shutil
import signal
import subprocess
import xml.etree.ElementTree as ET

from opp_repl.common.compile import *
from opp_repl.simulation.project import *

_logger = logging.getLogger(__name__)


def _generate_opp_defines(simulation_project, makefile_inc_config):
    """
    Generates the opp_defines.h file containing #define for each WITH_*
    Makefile.inc variable whose value is "yes".
    """
    output_path = simulation_project.get_full_path(simulation_project.opp_defines_file)
    lines = ["// Generated file, do not edit\n"]
    for var_name in sorted(makefile_inc_config._vars.keys()):
        if var_name.startswith("WITH_") and makefile_inc_config.get(var_name) == "yes":
            lines.append(f"#ifndef {var_name}\n#define {var_name}\n#endif\n")
    content = "".join(lines)
    # Write only if changed
    if os.path.exists(output_path):
        with open(output_path, "r") as f:
            if f.read() == content:
                return
    output_dir = os.path.dirname(output_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    with open(output_path, "w") as f:
        f.write(content)
    _logger.info("Generated %s", output_path)


def generate_makefile(simulation_project=None, **kwargs):
    """
    Generates a Makefile for a simulation project by running :command:`opp_makemake`.

    The makemake options are read from the project's ``.oppbuildspec`` file.
    If no ``.oppbuildspec`` is found, sensible defaults (``--deep -f``) are used.
    When the project's :py:attr:`build_types` includes ``"executable"`` and no
    ``-o`` option is present, ``-o <project_name>`` is added automatically so
    that the resulting binary name matches what opp_repl expects.

    Parameters:
        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>`):
            The simulation project to generate a Makefile for. If unspecified, then the default simulation project is used.

    Returns (None):
        Nothing.
    """
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    cwd = simulation_project.get_full_path(".")
    oppbuildspec_path = os.path.join(cwd, ".oppbuildspec")
    if os.path.isfile(oppbuildspec_path):
        tree = ET.parse(oppbuildspec_path)
        root = tree.getroot()
        makemake_options = None
        for dir_elem in root.iter("dir"):
            if dir_elem.get("type") == "makemake" and dir_elem.get("path") == ".":
                makemake_options = dir_elem.get("makemake-options", "")
                break
        if makemake_options is None:
            for dir_elem in root.iter("dir"):
                if dir_elem.get("type") == "makemake":
                    makemake_options = dir_elem.get("makemake-options", "")
                    break
        options = shlex.split(makemake_options) if makemake_options else ["--deep", "-f"]
    else:
        options = ["--deep", "-f"]
    options = [opt for opt in options if not opt.startswith("--meta:")]
    if "executable" in simulation_project.build_types and not any(opt == "-o" for opt in options):
        options.extend(["-o", simulation_project.get_name()])
    args = ["opp_makemake"] + options
    name = simulation_project.get_name()
    _logger.info(f"Generating Makefile for {name}")
    if simulation_project.opp_env_workspace:
        shell_cmd = "cd " + shlex.quote(cwd) + " && " + shlex.join(args)
        args = ["opp_env", "-l", "WARN", "run", simulation_project.opp_env_project, "-w", simulation_project.opp_env_workspace, "-c", shell_cmd]
        run_command_with_logging(args, error_message=f"Generating Makefile for {name} failed")
    else:
        run_command_with_logging(args, cwd=cwd, env=simulation_project.get_env(), error_message=f"Generating Makefile for {name} failed")
    _logger.info(f"Generating Makefile for {name} done")

def make_makefiles(simulation_project=None, **kwargs):
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    args = ["make", "makefiles"]
    cwd = simulation_project.get_full_path(".")
    if simulation_project.opp_env_workspace:
        shell_cmd = "cd " + shlex.quote(cwd) + " && " + shlex.join(args)
        args = ["opp_env", "-l", "WARN", "run", simulation_project.opp_env_project, "-w", simulation_project.opp_env_workspace, "-c", shell_cmd]
        run_command_with_logging(args, error_message=f"Making {simulation_project.get_name()} makefiles failed")
    else:
        run_command_with_logging(args, cwd=cwd, env=simulation_project.get_env(), error_message=f"Making {simulation_project.get_name()} makefiles failed")

def build_project(build_mode="makefile", **kwargs):
    """
    Builds all output files of a simulation project using either :py:func:`build_project_using_makefile` or :py:func:`build_project_using_tasks`.

    Parameters:
        build_mode (string):
            Specifies the requested build mode. Valid values are "makefile" and "task".

        kwargs (dict):
            Additional parameters are inherited from :py:func:`build_project_using_makefile` and :py:func:`build_project_using_tasks` functions.

    Returns (None):
        Nothing.
    """
    if build_mode == "makefile":
        build_function = build_project_using_makefile
    elif build_mode == "task":
        build_function = build_project_using_tasks
    else:
        raise Exception(f"Unknown build_mode argument: {build_mode}")
    return build_function(**kwargs)

def is_build_up_to_date(simulation_project=None, mode="release", **kwargs):
    """
    Checks whether a simulation project is already up to date by running :command:`make -q`.

    Parameters:
        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>`):
            The simulation project to check. If unspecified, then the default simulation project is used.

        mode (string):
            Specifies the build mode to check. Valid values are "debug" and "release".

    Returns (bool):
        True if the project is up to date, False otherwise.
    """
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    cwd = simulation_project.get_full_path(".")
    if not os.path.isfile(os.path.join(cwd, "Makefile")):
        return False
    args = ["make", "-q", "MODE=" + mode]
    if simulation_project.opp_env_workspace:
        shell_cmd = "cd " + shlex.quote(cwd) + " && " + shlex.join(args)
        args = ["opp_env", "-l", "WARN", "run", simulation_project.opp_env_project, "-w", simulation_project.opp_env_workspace, "-c", shell_cmd]
        result = subprocess.run(args, capture_output=True)
    else:
        result = subprocess.run(args, cwd=cwd, env=simulation_project.get_env(), capture_output=True)
    return result.returncode == 0

def build_project_using_makefile(simulation_project=None, mode="release", **kwargs):
    """
    Builds a simulation project using the Makefile generated by the command line tool :command:`opp_makemake`. The
    output files include executables, dynamic libraries, static libraries, C++ object files, C++ message file headers
    and their implementations, etc.

    Parameters:
        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>`):
            The simulation project to build. If unspecified, then the default simulation project is used.

        mode (string):
            Specifies the build mode of the output binaries. Valid values are "debug" and "release".

    Returns (None):
        Nothing.
    """
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    cwd = simulation_project.get_full_path(".")
    if not os.path.isfile(os.path.join(cwd, "Makefile")):
        _logger.info(f"No Makefile found in {cwd}, generating one")
        generate_makefile(simulation_project=simulation_project)
    if not is_build_up_to_date(simulation_project=simulation_project, mode=mode):
        _logger.info(f"Building {simulation_project.get_name()} in {mode} mode started")
        args = ["make", "MODE=" + mode, "-j", str(multiprocessing.cpu_count())]
        if simulation_project.opp_env_workspace:
            shell_cmd = "cd " + shlex.quote(cwd) + " && " + shlex.join(args)
            args = ["opp_env", "-l", "WARN", "run", simulation_project.opp_env_project, "-w", simulation_project.opp_env_workspace, "-c", shell_cmd]
            run_command_with_logging(args, error_message=f"Building {simulation_project.get_name()} failed")
        else:
            run_command_with_logging(args, cwd=cwd, env=simulation_project.get_env(), error_message=f"Building {simulation_project.get_name()} failed")
        _logger.info(f"Building {simulation_project.get_name()} in {mode} mode ended")

class MultipleBuildTasks(MultipleTasks):
    def __init__(self, simulation_project=None, concurrent=True, multiple_task_results_class=MultipleBuildTaskResults, **kwargs):
        super().__init__(concurrent=concurrent, multiple_task_results_class=multiple_task_results_class, **kwargs)
        self.simulation_project = simulation_project

    def get_description(self):
        return self.simulation_project.get_name() + " " + super().get_description()

    def is_up_to_date(self):
        def get_file_modification_time(file_path):
            full_file_path = self.simulation_project.get_full_path(file_path)
            return os.path.getmtime(full_file_path) if os.path.exists(full_file_path) else None
        def get_file_modification_times(file_paths):
            return list(map(get_file_modification_time, file_paths))
        input_file_modification_times = get_file_modification_times(self.get_input_files())
        output_file_modification_times = get_file_modification_times(self.get_output_files())
        return input_file_modification_times and output_file_modification_times and \
               not list(filter(lambda timestamp: timestamp is None, input_file_modification_times)) and \
               not list(filter(lambda timestamp: timestamp is None, output_file_modification_times)) and \
               max(input_file_modification_times) < min(output_file_modification_times)

    def get_input_files(self):
        input_files = []
        for task in self.tasks:
            input_files = input_files + task.get_input_files()
        return input_files

    def get_output_files(self):
        outpu_files = []
        for task in self.tasks:
            outpu_files = outpu_files + task.get_output_files()
        return outpu_files

class MultipleMsgCompileTasks(MultipleTasks):
    def __init__(self, simulation_project=None, name="MSG compile task", mode="release", concurrent=True, multiple_task_results_class=MultipleBuildTaskResults, **kwargs):
        super().__init__(name=name, mode=mode, concurrent=concurrent, multiple_task_results_class=multiple_task_results_class, **kwargs)
        self.simulation_project = simulation_project
        self.mode = mode

    def get_description(self):
        return self.simulation_project.get_name() + " " + super().get_description()

    def is_up_to_date(self):
        return all(t.is_up_to_date() for t in self.tasks)

    def run_protected(self, **kwargs):
        result = super().run_protected(**kwargs)
        for task_result in result.results:
            if task_result.result == "DONE":
                for output_file in task_result.task.get_output_files():
                    os.utime(self.simulation_project.get_full_path(output_file), None)
        return result

class MultipleCppCompileTasks(MultipleTasks):
    def __init__(self, simulation_project=None, name="C++ compile task", mode="release", concurrent=True, multiple_task_results_class=MultipleBuildTaskResults, **kwargs):
        super().__init__(name=name, mode=mode, concurrent=concurrent, multiple_task_results_class=multiple_task_results_class, **kwargs)
        self.simulation_project = simulation_project
        self.mode = mode

    def get_description(self):
        return self.simulation_project.get_name() + " " + super().get_description()

    def is_up_to_date(self):
        return all(t.is_up_to_date() for t in self.tasks)

    def run_protected(self, **kwargs):
        result = super().run_protected(**kwargs)
        for task_result in result.results:
            if task_result.result == "DONE":
                for output_file in task_result.task.get_output_files():
                    os.utime(self.simulation_project.get_full_path(output_file), None)
        return result


def _filter_mf_flags(flags):
    """Drop -MF and its argument from a flags list."""
    filtered = []
    skip_next = False
    for f in flags:
        if skip_next:
            skip_next = False
            continue
        if f == "-MF":
            skip_next = True
            continue
        if f.startswith("-MF"):
            continue
        filtered.append(f)
    return filtered


def _simulation_project_output_folder(simulation_project, mode, makefile_inc_config):
    if makefile_inc_config:
        return f"out/{makefile_inc_config.configname}"
    return f"out/clang-{mode}"


class SimulationProjectMsgCompileTask(MsgCompileTask):
    """
    Derived ``MsgCompileTask`` that materializes its parameters from a
    ``SimulationProject`` and an optional ``MakefileIncConfig``.
    """

    def __init__(self, simulation_project=None, file_path=None, mode="release", makefile_inc_config=None, **kwargs):
        self.simulation_project = simulation_project
        self.file_path = file_path
        self.mode = mode
        self.makefile_inc_config = makefile_inc_config

        output_folder = _simulation_project_output_folder(simulation_project, mode, makefile_inc_config)
        header_file = re.sub(r"\.msg$", "_m.h", file_path)
        cpp_file = re.sub(r"\.msg$", "_m.cc", file_path)
        dependency_file = f"{output_folder}/{header_file}.d"

        msgc = makefile_inc_config.msgc if makefile_inc_config else "opp_msgc"
        import_paths = simulation_project.get_effective_msg_folders()
        include_paths = simulation_project.get_effective_include_folders()
        dll_symbol = simulation_project.dll_symbol

        super().__init__(
            working_dir=simulation_project.get_full_path("."),
            msgc=msgc,
            flags=["--msg6", "-s", "_m.cc"],
            import_paths=import_paths,
            include_paths=include_paths,
            dll_symbol=dll_symbol,
            input_file=file_path,
            output_files=[cpp_file, header_file],
            dependency_file=dependency_file,
            **kwargs,
        )

    def get_parameters_string(self, **kwargs):
        return re.sub(r"\.msg$", "_m.cc", self.file_path)

    def get_input_files(self):
        # If a dependency file has been emitted, use it; resolve recorded paths
        # relative to the project's src/ folder (legacy convention).
        dep = self._resolve(self.dependency_file)
        if dep and os.path.exists(dep):
            dependency = read_dependency_file(dep)
            object_path = re.sub(r"\.msg$", "_m.cc", self.file_path)
            key = re.sub(r"^src/", "", object_path)
            if key in dependency:
                return [os.path.join("src", p) for p in dependency[key]]
        return [self.file_path]


class SimulationProjectCppCompileTask(CppCompileTask):
    """
    Derived ``CppCompileTask`` that materializes its parameters from a
    ``SimulationProject`` and an optional ``MakefileIncConfig``.
    """

    def __init__(self, simulation_project=None, file_path=None, mode="release", makefile_inc_config=None, feature_cflags=None, **kwargs):
        self.simulation_project = simulation_project
        self.file_path = file_path
        self.mode = mode
        self.makefile_inc_config = makefile_inc_config
        self.feature_cflags = feature_cflags or []

        output_folder = _simulation_project_output_folder(simulation_project, mode, makefile_inc_config)
        output_file = f"{output_folder}/" + re.sub(r"\.cc$", ".o", file_path)
        dependency_file = f"{output_file}.d"

        if makefile_inc_config:
            cxx_parts = shlex.split(makefile_inc_config.cxx)
            cflags = _filter_mf_flags(shlex.split(makefile_inc_config.cflags))
            cxxflags = shlex.split(makefile_inc_config.cxxflags)
            import_defines = shlex.split(makefile_inc_config.import_defines) if makefile_inc_config.import_defines else []
            incl_dir = makefile_inc_config.omnetpp_incl_dir
        else:
            cxx_parts = ["clang++"]
            cflags = ["-O3", "-DNDEBUG=1", "-MMD", "-MP", "-fPIC",
                      "-Wno-deprecated-register", "-Wno-unused-function", "-fno-omit-frame-pointer"]
            cxxflags = ["-std=c++20"]
            import_defines = ["-DOMNETPPLIBS_IMPORT"]
            incl_dir = "/usr/include"

        dll_defines = [f"-D{simulation_project.dll_symbol}_EXPORT"] if simulation_project.dll_symbol else []
        project_defines = [f"-D{d}" for d in simulation_project.cpp_defines]
        include_dirs = [incl_dir, *simulation_project.get_effective_include_folders(), *simulation_project.external_include_folders]
        extra_cflags = getattr(simulation_project, "extra_cflags", []) or []

        super().__init__(
            working_dir=simulation_project.get_full_path("."),
            compiler=cxx_parts,
            cxxflags=cxxflags,
            cflags=cflags,
            defines=[*import_defines, *dll_defines, *project_defines],
            include_dirs=include_dirs,
            input_file=file_path,
            output_file=output_file,
            dependency_file=dependency_file,
            extra_args=[*self.feature_cflags, *extra_cflags],
            **kwargs,
        )

    def get_parameters_string(self, **kwargs):
        return self.file_path

    def get_input_files(self):
        dep = self._resolve(self.dependency_file)
        if dep and os.path.exists(dep):
            dependency = read_dependency_file(dep)
            if self.output_file in dependency:
                return dependency[self.output_file]
        return [self.file_path]


class SimulationProjectLinkTask(LinkTask):
    """
    Derived ``LinkTask`` that materializes its parameters from a
    ``SimulationProject`` + ``MakefileIncConfig``. ``build_type`` is one of
    ``"executable"``, ``"dynamic library"``, ``"static library"``.
    """

    _BUILD_TYPE_TO_BASE_TYPE = {
        "executable": "executable",
        "dynamic library": "shared",
        "static library": "static",
    }

    def __init__(self, simulation_project=None, build_type="dynamic library", mode="release",
                 compile_tasks=None, makefile_inc_config=None, feature_ldflags=None, **kwargs):
        self.simulation_project = simulation_project
        self.build_type = build_type
        self.mode = mode
        self.compile_tasks = compile_tasks or []
        self.makefile_inc_config = makefile_inc_config
        self.feature_ldflags = feature_ldflags or []

        sp = simulation_project
        cfg = makefile_inc_config

        output_folder = _simulation_project_output_folder(sp, mode, cfg)
        output_prefix = "" if build_type == "executable" else (cfg.lib_prefix if cfg else "lib")
        output_suffix = cfg.debug_suffix if cfg else ("_dbg" if mode == "debug" else "")
        if cfg:
            output_ext = cfg.exe_suffix if build_type == "executable" else (cfg.shared_lib_suffix if build_type == "dynamic library" else cfg.a_lib_suffix)
        else:
            output_ext = "" if build_type == "executable" else (".so" if build_type == "dynamic library" else ".a")
        base_name = sp.dynamic_libraries[0]
        output_file = os.path.join(output_folder, output_prefix + base_name + output_suffix + output_ext)

        input_files = flatten(map(lambda t: t.get_output_files(), self.compile_tasks))

        # Resolve dependency project library paths
        from opp_repl.simulation.project import get_simulation_project
        used_lib_paths = []
        used_lib_names = []
        for used_project_name in sp.used_projects:
            used_proj = get_simulation_project(used_project_name, None)
            lib_path = used_proj.get_library_folder_full_path()
            if lib_path:
                used_lib_paths.append(lib_path)
            if used_proj.dynamic_libraries:
                used_lib_names.append(used_proj.dynamic_libraries[0])

        extra_ldflags = getattr(sp, "extra_ldflags", []) or []
        debug_suffix = cfg.debug_suffix if cfg else ("_dbg" if mode == "debug" else "")

        library_dirs = [*used_lib_paths, *sp.external_library_folders]
        rpath_dirs = list(used_lib_paths)

        if build_type == "executable":
            if cfg:
                linker = shlex.split(cfg.cxx)
                ldflags = shlex.split(cfg.ldflags)
                all_env_libs = shlex.split(cfg.all_env_libs)
                kernel_libs = shlex.split(cfg.kernel_libs)
                sys_libs = shlex.split(cfg.sys_libs)
                oppmain_lib = shlex.split(cfg.oppmain_lib)
            else:
                linker = ["clang++"]
                ldflags = ["-fuse-ld=lld", "-Wl,--export-dynamic"]
                all_env_libs = ["-loppcmdenv", "-loppenvir", "-loppqtenv", "-loppenvir", "-lopplayout"]
                kernel_libs = ["-loppsim"]
                sys_libs = ["-lstdc++"]
                oppmain_lib = ["-loppmain"]

            libraries = [*oppmain_lib, *all_env_libs, *kernel_libs,
                         *[f"-l{n}" for n in used_lib_names],
                         *[f"-l{lib}" for lib in sp.external_libraries],
                         *self.feature_ldflags,
                         *extra_ldflags,
                         *sys_libs]
            super().__init__(
                working_dir=sp.get_full_path("."),
                linker=linker,
                ldflags=ldflags,
                input_files=input_files,
                output_file=output_file,
                libraries=libraries,
                library_dirs=library_dirs,
                rpath_dirs=rpath_dirs,
                type="executable",
                **kwargs,
            )

        elif build_type == "dynamic library":
            if cfg:
                linker = shlex.split(cfg.shlib_ld)
                ldflags = shlex.split(cfg.ldflags)
                kernel_libs = shlex.split(cfg.kernel_libs)
                sys_libs = shlex.split(cfg.sys_libs)
                as_needed_off = cfg.as_needed_off
                whole_archive_on = cfg.whole_archive_on
                whole_archive_off = cfg.whole_archive_off
            else:
                linker = ["clang++", "-shared", "-fPIC"]
                ldflags = ["-fuse-ld=lld", "-Wl,--export-dynamic"]
                kernel_libs = ["-loppsim"]
                sys_libs = ["-lstdc++"]
                as_needed_off = "-Wl,--no-as-needed"
                whole_archive_on = "-Wl,--whole-archive"
                whole_archive_off = "-Wl,--no-whole-archive"

            libraries = [as_needed_off, whole_archive_on, whole_archive_off,
                         f"-loppenvir{debug_suffix}",
                         *kernel_libs,
                         *[f"-l{n}" for n in used_lib_names],
                         *[f"-l{lib}" for lib in sp.external_libraries],
                         *self.feature_ldflags,
                         *extra_ldflags,
                         *sys_libs]
            super().__init__(
                working_dir=sp.get_full_path("."),
                linker=linker,
                ldflags=ldflags,
                input_files=input_files,
                output_file=output_file,
                libraries=libraries,
                library_dirs=library_dirs,
                rpath_dirs=rpath_dirs,
                type="shared",
                **kwargs,
            )

        else:  # static library
            ar = shlex.split(cfg.ar_cr) if cfg else ["ar", "cr"]
            super().__init__(
                working_dir=sp.get_full_path("."),
                input_files=input_files,
                output_file=output_file,
                type="static",
                ar=ar,
                **kwargs,
            )

    def get_parameters_string(self, **kwargs):
        return os.path.basename(self.output_file)


class SimulationProjectCopyBinaryTask(CopyBinaryTask):
    """
    Derived ``CopyBinaryTask`` that copies one of a simulation project's built
    binaries (executable / library) from the build output folder to the
    project's ``bin_folder`` / ``library_folder``.
    """

    def __init__(self, simulation_project=None, build_type="dynamic library", name=None,
                 mode="release", makefile_inc_config=None, **kwargs):
        self.simulation_project = simulation_project
        self.build_type = build_type
        self.name = name
        self.mode = mode
        self.makefile_inc_config = makefile_inc_config

        output_folder = _simulation_project_output_folder(simulation_project, mode, makefile_inc_config)
        if makefile_inc_config:
            output_prefix = "" if build_type == "executable" else makefile_inc_config.lib_prefix
            output_suffix = makefile_inc_config.debug_suffix
            output_ext = makefile_inc_config.exe_suffix if build_type == "executable" else (makefile_inc_config.shared_lib_suffix if build_type == "dynamic library" else makefile_inc_config.a_lib_suffix)
        else:
            output_prefix = "" if build_type == "executable" else "lib"
            output_suffix = "_dbg" if mode == "debug" else ""
            output_ext = "" if build_type == "executable" else (".so" if build_type == "dynamic library" else ".a")

        filename = output_prefix + name + output_suffix + output_ext
        target_dir = simulation_project.bin_folder if build_type == "executable" else simulation_project.library_folder

        super().__init__(
            working_dir=simulation_project.get_full_path("."),
            source_file=os.path.join(output_folder, filename),
            target_file=os.path.join(target_dir, filename),
            name="copy binary task",
            **kwargs,
        )

class BuildSimulationProjectTask(MultipleTasks):
    """
    Represents a task that builds a simulation project.
    """

    def __init__(self, simulation_project, name="build task", mode="release", concurrent=True, multiple_task_results_class=MultipleBuildTaskResults, **kwargs):
        """
        Initializes a new build simulation project task.

        Parameters:
            concurrent (bool):
                Flag specifying whether the build is allowed to run sub-tasks concurrently or not.

            mode (string):
                Specifies the build mode for the output binaries. Valie values are "debug" and "release".
        """
        super().__init__(concurrent=False, name=name, mode=mode, multiple_task_results_class=multiple_task_results_class, **kwargs)
        self.simulation_project = simulation_project
        self.mode = mode
        self.concurrent_child_tasks = concurrent
        self.tasks = self.get_build_tasks(mode=mode, **kwargs)

    def is_up_to_date(self):
        return all(t.is_up_to_date() for t in self.tasks)

    def get_description(self):
        return self.simulation_project.get_name() + " " + super().get_description()

    def get_build_tasks(self, **kwargs):
        # Get Makefile.inc configuration from the OMNeT++ project
        makefile_inc_config = None
        feature_cflags = []
        feature_ldflags = []
        omnetpp_project = self.simulation_project.get_omnetpp_project()
        if omnetpp_project:
            makefile_inc_config = omnetpp_project.get_makefile_inc_config(self.mode)

        # Get feature flags if the project has .oppfeatures
        from opp_repl.simulation.features import has_features, get_feature_cflags, get_feature_ldflags, generate_features_header, resolve_feature_libraries
        if has_features(self.simulation_project):
            feature_cflags = get_feature_cflags(self.simulation_project)
            feature_ldflags = get_feature_ldflags(self.simulation_project)
            generate_features_header(self.simulation_project)

        # Resolve feature-conditional libraries (pkg-config, Makefile.inc vars)
        feat_lib_cflags, feat_lib_ldflags = resolve_feature_libraries(self.simulation_project, makefile_inc_config)
        feature_cflags = feature_cflags + feat_lib_cflags
        feature_ldflags = feature_ldflags + feat_lib_ldflags

        # Generate opp_defines.h from WITH_* Makefile.inc variables
        if self.simulation_project.opp_defines_file and makefile_inc_config:
            _generate_opp_defines(self.simulation_project, makefile_inc_config)

        # Determine output folder and ensure it exists
        if makefile_inc_config:
            output_folder = self.simulation_project.get_full_path(f"out/{makefile_inc_config.configname}")
        else:
            output_folder = self.simulation_project.get_full_path(f"out/clang-{self.mode}")
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        msg_compile_tasks = [SimulationProjectMsgCompileTask(simulation_project=self.simulation_project, file_path=msg_file, mode=self.mode, makefile_inc_config=makefile_inc_config) for msg_file in self.simulation_project.get_msg_files()]
        multiple_msg_compile_tasks = MultipleMsgCompileTasks(simulation_project=self.simulation_project, mode=self.mode, tasks=msg_compile_tasks, concurrent=self.concurrent_child_tasks)
        msg_cpp_compile_tasks = [SimulationProjectCppCompileTask(simulation_project=self.simulation_project, file_path=re.sub(r"\.msg$", "_m.cc", msg_file), mode=self.mode, makefile_inc_config=makefile_inc_config, feature_cflags=feature_cflags) for msg_file in self.simulation_project.get_msg_files()]
        cpp_compile_tasks = [SimulationProjectCppCompileTask(simulation_project=self.simulation_project, file_path=cpp_file, mode=self.mode, makefile_inc_config=makefile_inc_config, feature_cflags=feature_cflags) for cpp_file in self.simulation_project.get_cpp_files()]
        all_cpp_compile_tasks = msg_cpp_compile_tasks + cpp_compile_tasks
        multiple_cpp_compile_tasks = MultipleCppCompileTasks(simulation_project=self.simulation_project, mode=self.mode, tasks=all_cpp_compile_tasks, concurrent=self.concurrent_child_tasks)
        link_tasks = flatten([[SimulationProjectLinkTask(simulation_project=self.simulation_project, build_type=build_type, mode=self.mode, compile_tasks=all_cpp_compile_tasks, makefile_inc_config=makefile_inc_config, feature_ldflags=feature_ldflags) for build_type in self.simulation_project.build_types] for _ in self.simulation_project.executables])
        multiple_link_tasks = MultipleBuildTasks(simulation_project=self.simulation_project, tasks=link_tasks, name="link task", concurrent=self.concurrent_child_tasks)
        copy_binary_tasks = []
        for build_type in self.simulation_project.build_types:
            if build_type == "executable":
                names = self.simulation_project.executables
            elif build_type == "dynamic library":
                names = self.simulation_project.dynamic_libraries
            else:
                names = self.simulation_project.static_libraries
            for name in names:
                copy_binary_tasks.append(SimulationProjectCopyBinaryTask(simulation_project=self.simulation_project, build_type=build_type, name=name, mode=self.mode, makefile_inc_config=makefile_inc_config))
        multiple_copy_binary_tasks = MultipleBuildTasks(simulation_project=self.simulation_project, tasks=copy_binary_tasks, name="copy task", concurrent=self.concurrent_child_tasks)
        all_tasks = []
        if multiple_msg_compile_tasks.tasks:
            all_tasks.append(multiple_msg_compile_tasks)
        if multiple_cpp_compile_tasks.tasks:
            all_tasks.append(multiple_cpp_compile_tasks)
            all_tasks.append(multiple_link_tasks)
            all_tasks.append(multiple_copy_binary_tasks)
        return all_tasks

def build_project_using_tasks(simulation_project, **kwargs):
    """
    Builds all output files of a simulation project using tasks. The output files include executables, dynamic libraries,
    static libraries, C++ object files, C++ message file headers and their implementations, etc.

    Parameters:
        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>`):
            The simulation project to build. If unspecified, then the default simulation project is used.

        kwargs (dict):
            Additional parameters are inherited from the constructor of :py:class:`BuildSimulationProjectTask`.

    Returns (None):
        Nothing.
    """
    build_task = BuildSimulationProjectTask(simulation_project, **dict(kwargs))
    build_task.log_structure()
    return build_task.run(**kwargs)

def clean_project(simulation_project=None, mode="release", build_mode="makefile", **kwargs):
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    if build_mode == "task":
        return clean_project_using_tasks(simulation_project, mode=mode, **kwargs)
    else:
        return clean_project_using_makefile(simulation_project, mode=mode, **kwargs)

def clean_project_using_makefile(simulation_project, mode="release", **kwargs):
    _logger.info(f"Cleaning {simulation_project.get_name()} started")
    cwd = simulation_project.get_full_path(".")
    if not os.path.isfile(os.path.join(cwd, "Makefile")):
        _logger.info(f"Cleaning {simulation_project.get_name()} skipped (no Makefile)")
        return
    args = ["make", "MODE=" + mode, "-j", str(multiprocessing.cpu_count()), "clean"]
    if simulation_project.opp_env_workspace:
        shell_cmd = "cd " + shlex.quote(cwd) + " && " + shlex.join(args)
        args = ["opp_env", "-l", "WARN", "run", simulation_project.opp_env_project, "-w", simulation_project.opp_env_workspace, "-c", shell_cmd]
        run_command_with_logging(args)
    else:
        run_command_with_logging(args, cwd=cwd, env=simulation_project.get_env())
    _logger.info(f"Cleaning {simulation_project.get_name()} ended")

class CleanFileTask(Task):
    def __init__(self, simulation_project=None, file_path=None, name="clean file task", **kwargs):
        super().__init__(name=name, action="Removing", **kwargs)
        self.simulation_project = simulation_project
        self.file_path = file_path

    def get_description(self):
        return self.file_path

    def get_parameters_string(self, **kwargs):
        return self.file_path

    def is_up_to_date(self):
        return not os.path.exists(self.simulation_project.get_full_path(self.file_path))

    def run_protected(self, **kwargs):
        full_path = self.simulation_project.get_full_path(self.file_path)
        if os.path.exists(full_path):
            os.remove(full_path)
        return self.task_result_class(task=self, result="DONE")

class CleanDirectoryTask(Task):
    def __init__(self, simulation_project=None, directory_path=None, name="clean directory task", **kwargs):
        super().__init__(name=name, action="Removing", **kwargs)
        self.simulation_project = simulation_project
        self.directory_path = directory_path

    def get_description(self):
        return self.directory_path

    def get_parameters_string(self, **kwargs):
        return self.directory_path

    def is_up_to_date(self):
        return not os.path.exists(self.simulation_project.get_full_path(self.directory_path))

    def run_protected(self, **kwargs):
        full_path = self.simulation_project.get_full_path(self.directory_path)
        if os.path.exists(full_path):
            shutil.rmtree(full_path)
        return self.task_result_class(task=self, result="DONE")

class MultipleCleanTasks(MultipleTasks):
    def is_up_to_date(self):
        return all(t.is_up_to_date() for t in self.tasks)

class CleanSimulationProjectTask(MultipleCleanTasks):
    def __init__(self, simulation_project=None, name="clean task", mode="release", **kwargs):
        super().__init__(concurrent=False, name=name, **kwargs)
        self.simulation_project = simulation_project
        self.mode = mode
        self.tasks = self.get_clean_tasks()

    def get_description(self):
        return self.simulation_project.get_name() + " " + super().get_description()

    def get_clean_tasks(self):
        tasks = []
        # Generated MSG files (_m.cc, _m.h)
        msg_clean_tasks = []
        for msg_file in self.simulation_project.get_msg_files():
            for suffix in ["_m.cc", "_m.h"]:
                generated_file = re.sub(r"\.msg", suffix, msg_file)
                msg_clean_tasks.append(CleanFileTask(simulation_project=self.simulation_project, file_path=generated_file))
        if msg_clean_tasks:
            tasks.append(MultipleCleanTasks(tasks=msg_clean_tasks, name="clean generated MSG file", concurrent=True))
        # Copied binaries
        binary_clean_tasks = []
        for build_type in self.simulation_project.build_types:
            if build_type == "executable":
                for executable in self.simulation_project.executables:
                    binary_clean_tasks.append(CleanFileTask(simulation_project=self.simulation_project, file_path=os.path.join(self.simulation_project.bin_folder, executable)))
            elif build_type == "dynamic library":
                for library in self.simulation_project.dynamic_libraries:
                    binary_clean_tasks.append(CleanFileTask(simulation_project=self.simulation_project, file_path=os.path.join(self.simulation_project.library_folder, "lib" + library + ".so")))
        if binary_clean_tasks:
            tasks.append(MultipleCleanTasks(tasks=binary_clean_tasks, name="clean binary", concurrent=True))
        # Output directory
        tasks.append(CleanDirectoryTask(simulation_project=self.simulation_project, directory_path="out"))
        return tasks

def clean_project_using_tasks(simulation_project, mode="release", **kwargs):
    clean_task = CleanSimulationProjectTask(simulation_project, mode=mode)
    clean_task.log_structure()
    return clean_task.run(**kwargs)
