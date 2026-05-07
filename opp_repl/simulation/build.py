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
        self.input_files = list(map(lambda input_file: self.simulation_project.get_full_path(input_file), self.simulation_project.get_msg_files()))
        self.output_files = list(map(lambda output_file: re.sub(r"\.msg", "_m.cc", output_file), self.input_files)) + \
                            list(map(lambda output_file: re.sub(r"\.msg", "_m.h", output_file), self.input_files))

    def get_description(self):
        return self.simulation_project.get_name() + " " + super().get_description()

    def is_up_to_date(self):
        def get_file_modification_time(file_path):
            full_file_path = self.simulation_project.get_full_path(file_path)
            return os.path.getmtime(full_file_path) if os.path.exists(full_file_path) else None
        def get_file_modification_times(file_paths):
            return list(map(get_file_modification_time, file_paths))
        input_file_modification_times = get_file_modification_times(self.input_files)
        output_file_modification_times = get_file_modification_times(self.output_files)
        return input_file_modification_times and output_file_modification_times and \
               not list(filter(lambda timestamp: timestamp is None, input_file_modification_times)) and \
               not list(filter(lambda timestamp: timestamp is None, output_file_modification_times)) and \
               max(input_file_modification_times) < min(output_file_modification_times)

    def run_protected(self, **kwargs):
        result = super().run_protected(**kwargs)
        for output_file in self.output_files:
            os.utime(self.simulation_project.get_full_path(output_file), None)
        return result

class MultipleCppCompileTasks(MultipleTasks):
    def __init__(self, simulation_project=None, name="C++ compile task", mode="release", concurrent=True, multiple_task_results_class=MultipleBuildTaskResults, **kwargs):
        super().__init__(name=name, mode=mode, concurrent=concurrent, multiple_task_results_class=multiple_task_results_class, **kwargs)
        self.simulation_project = simulation_project
        self.mode = mode
        input_files = self.simulation_project.get_cpp_files() + self.simulation_project.get_header_files()
        self.input_files = list(map(lambda input_file: self.simulation_project.get_full_path(input_file), input_files))
        self.output_files = list(map(lambda output_file: self.simulation_project.get_full_path(output_file), self.get_object_files()))

    def get_description(self):
        return self.simulation_project.get_name() + " " + super().get_description()

    def get_object_files(self):
        output_folder = f"out/clang-{self.mode}"
        object_files = []
        for cpp_folder in self.simulation_project.cpp_folders:
            file_paths = glob.glob(self.simulation_project.get_full_path(os.path.join(cpp_folder, "**/*.cc")), recursive=True)
            object_files = object_files + list(map(lambda file_path: os.path.join(output_folder, self.simulation_project.get_relative_path(re.sub(r"\.cc", ".o", file_path))), file_paths))
        return object_files

    def is_up_to_date(self):
        def get_file_modification_time(file_path):
            full_file_path = self.simulation_project.get_full_path(file_path)
            return os.path.getmtime(full_file_path) if os.path.exists(full_file_path) else None
        def get_file_modification_times(file_paths):
            return list(map(get_file_modification_time, file_paths))
        input_file_modification_times = get_file_modification_times(self.input_files)
        output_file_modification_times = get_file_modification_times(self.output_files)
        return input_file_modification_times and output_file_modification_times and \
               not list(filter(lambda timestamp: timestamp is None, input_file_modification_times)) and \
               not list(filter(lambda timestamp: timestamp is None, output_file_modification_times)) and \
               max(input_file_modification_times) < min(output_file_modification_times)

    def run_protected(self, **kwargs):
        result = super().run_protected(**kwargs)
        for output_file in self.output_files:
            os.utime(self.simulation_project.get_full_path(output_file), None)
        return result

class CopyBinaryTask(BuildTask):
    def __init__(self, simulation_project=None, name="copy binaries task", type="dynamic library", mode="release", makefile_inc_config=None, task_result_class=BuildTaskResult, **kwargs):
        super().__init__(simulation_project=simulation_project, name=name, task_result_class=task_result_class, **kwargs)
        self.type = type
        self.mode = mode
        self.makefile_inc_config = makefile_inc_config

    def get_action_string(self, **kwargs):
        return "Copying"

    def get_parameters_string(self, **kwargs):
        return (self.type + "s" if self.type == "executable" else self.type[:-1] + "ies")

    def get_output_folder(self):
        if self.makefile_inc_config:
            return f"out/{self.makefile_inc_config.configname}"
        return f"out/clang-{self.mode}"

    def get_output_prefix(self):
        if self.makefile_inc_config:
            return "" if self.type == "executable" else self.makefile_inc_config.lib_prefix
        return "" if self.type == "executable" else "lib"

    def get_output_suffix(self):
        if self.makefile_inc_config:
            return self.makefile_inc_config.debug_suffix
        return "_dbg" if self.mode == "debug" else ""

    def get_output_extension(self):
        if self.makefile_inc_config:
            if self.type == "executable":
                return self.makefile_inc_config.exe_suffix
            elif self.type == "dynamic library":
                return self.makefile_inc_config.shared_lib_suffix
            else:
                return self.makefile_inc_config.a_lib_suffix
        return "" if self.type == "executable" else (".so" if self.type == "dynamic library" else ".a")

    def get_input_files(self):
        result = []
        output_folder = self.get_output_folder()
        if self.type == "executable":
            for executable in self.simulation_project.executables:
                result.append(os.path.join(output_folder, executable + self.get_output_suffix()))
        else:
            for library in (self.simulation_project.dynamic_libraries if self.type == "dynamic library" else self.simulation_project.static_libraries):
                library_file_name = self.get_output_prefix() + library + self.get_output_suffix() + self.get_output_extension()
                result.append(os.path.join(output_folder, library_file_name))
        return result

    def get_output_files(self):
        result = []
        if self.type == "executable":
            for executable in self.simulation_project.executables:
                result.append(os.path.join(self.simulation_project.bin_folder, executable + self.get_output_suffix()))
        else:
            for library in (self.simulation_project.dynamic_libraries if self.type == "dynamic library" else self.simulation_project.static_libraries):
                library_file_name = self.get_output_prefix() + library + self.get_output_suffix() + self.get_output_extension()
                result.append(os.path.join(self.simulation_project.library_folder, library_file_name))
        return result

    def run_protected(self, **kwargs):
        for output_file in self.get_output_files():
            full_path = self.simulation_project.get_full_path(output_file)
            if os.path.exists(full_path):
                os.remove(full_path)
        for input_file, output_file in zip(self.get_input_files(), self.get_output_files()):
            shutil.copy(self.simulation_project.get_full_path(input_file), self.simulation_project.get_full_path(output_file))
        return self.task_result_class(task=self, result="DONE")

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

        msg_compile_tasks = list(map(lambda msg_file: MsgCompileTask(simulation_project=self.simulation_project, file_path=msg_file, mode=self.mode, makefile_inc_config=makefile_inc_config), self.simulation_project.get_msg_files()))
        multiple_msg_compile_tasks = MultipleMsgCompileTasks(simulation_project=self.simulation_project, mode=self.mode, tasks=msg_compile_tasks, concurrent=self.concurrent_child_tasks)
        msg_cpp_compile_tasks = list(map(lambda msg_file: CppCompileTask(simulation_project=self.simulation_project, file_path=re.sub(r"\.msg", "_m.cc", msg_file), mode=self.mode, makefile_inc_config=makefile_inc_config, feature_cflags=feature_cflags), self.simulation_project.get_msg_files()))
        cpp_compile_tasks = list(map(lambda cpp_file: CppCompileTask(simulation_project=self.simulation_project, file_path=cpp_file, mode=self.mode, makefile_inc_config=makefile_inc_config, feature_cflags=feature_cflags), self.simulation_project.get_cpp_files()))
        all_cpp_compile_tasks = msg_cpp_compile_tasks + cpp_compile_tasks
        multiple_cpp_compile_tasks = MultipleCppCompileTasks(simulation_project=self.simulation_project, mode=self.mode, tasks=all_cpp_compile_tasks, concurrent=self.concurrent_child_tasks)
        link_tasks = flatten(map(lambda library: list(map(lambda build_type: LinkTask(simulation_project=self.simulation_project, type=build_type, mode=self.mode, compile_tasks=all_cpp_compile_tasks, makefile_inc_config=makefile_inc_config, feature_ldflags=feature_ldflags), self.simulation_project.build_types)), self.simulation_project.executables))
        multiple_link_tasks = MultipleBuildTasks(simulation_project=self.simulation_project, tasks=link_tasks, name="link task", concurrent=self.concurrent_child_tasks)
        copy_binary_tasks = list(map(lambda build_type: CopyBinaryTask(simulation_project=self.simulation_project, type=build_type, mode=self.mode, makefile_inc_config=makefile_inc_config), self.simulation_project.build_types))
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

def clean_project(simulation_project=None, mode="release", **kwargs):
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
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
