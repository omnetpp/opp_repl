"""
This module provides abstractions for simulation tasks and their results.
"""

import copy
import datetime
import functools
import hashlib
import logging
import os
import random
import re
import signal
import subprocess
import sys
import time

try:
    from omnetpp.scave.results import read_result_files, get_scalars as _get_scalars, get_vectors as _get_vectors, get_histograms as _get_histograms
except (ImportError, ModuleNotFoundError):
    pass

import pandas as pd

from opp_repl.common import *
from opp_repl.simulation.build import *
from opp_repl.simulation.config import *
from opp_repl.simulation.fingerprint import *
from opp_repl.simulation.project import *
from opp_repl.simulation.stdout import *
from opp_repl.simulation.subprocess import *
from opp_repl.simulation.opp_env_runner import *
from opp_repl.simulation.iderunner import *

_logger = logging.getLogger(__name__)

# TODO: the task result depends on the following:
#
# 1. Binary distribution
#  - command line arguments
#  - environment variables
#  - executables
#  - shared libraries
#  - INI files
#  - NED files
#  - Python files
#  - XML configuration files
#  - JSON configuration files
#
# 2. Source distribution
#  - command line arguments
#  - environment variables
#  - INI files
#  - NED files
#  - MSG files
#  - CC files
#  - H files
#  - Python files
#  - XML configuration files
#  - JSON configuration files
#
# 3. Complete distribution
#  - all files
#
# 4. Partial distribution
#  - only relevant files
#
class SimulationTaskResult(TaskResult):
    """
    Represents a simulation task result that is collected when a simulation task is run.

    Please note that undocumented features are not supposed to be called by the user.
    """

    def __init__(self, subprocess_result=None, cancel=False, **kwargs):
        super().__init__(**kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.subprocess_result = subprocess_result
        if subprocess_result:
            stdout = self.subprocess_result.stdout or ""
            stderr = self.subprocess_result.stderr or ""
            self.stdout = stdout
            self.stderr = stderr
            match = re.search(r"<!> Simulation time limit reached -- at t=(.*), event #(\d+)", stdout)
            self.last_event_number = int(match.group(2)) if match else None
            self.last_simulation_time = match.group(1) if match else None
            self.elapsed_cpu_time = None # TODO
            regex = r"<!> Error: (.*) -- in module \((.*?)\) (.*?) \(.*?\), at t=(.*?)s, event #(.*)"
            match = re.search(regex, stderr)
            if match:
                self.error_message = match.group(1)
                self.error_module = "(" + match.group(2) + ") " + match.group(3)
                self.error_simulation_time = match.group(4)
                self.error_event_number = int(match.group(5))
            else:
                match = re.search(regex, stdout)
                if match:
                    self.error_message = match.group(1)
                    self.error_module = "(" + match.group(2) + ") " + match.group(3)
                    self.error_simulation_time = match.group(4)
                    self.error_event_number = int(match.group(5))
                else:
                    self.error_message = None
                    self.error_module = None
                    self.error_simulation_time = None
                    self.error_event_number = None
            matching_lines = [re.sub(r"instantiated NED type: (.*)", "\\1", line) for line in stdout.split("\n") if re.search(r"inet\.", line)]
            self.used_types = sorted(list(set(matching_lines)))
            if self.error_message is None:
                match = re.search(r"<!> Error: (.*)", stderr)
                self.error_message = match.group(1).strip() if match else None
            if self.error_message:
                if re.search(r"The simulation attempted to prompt for user input", self.error_message):
                    self.result = "SKIP"
                    self.color = COLOR_CYAN
                    self.expected_result = "SKIP"
                    self.expected = True
                    self.reason = "Interactive simulation"
            match = re.search(r"Simulation CPU usage: elapsedTime = (.*?), numCycles = (.*?), numInstructions = (.*?)\n", subprocess_result.stdout)
            self.elapsed_cpu_time = float(match.group(1)) if match else None
            self.num_cpu_cycles = int(match.group(2)) if match else None
            self.num_cpu_instructions = int(match.group(3)) if match else None
            self.stdout_file_path = None
            self.eventlog_file_path = None
            self.scalar_file_path = None
            self.vector_file_path = None
        else:
            self.last_event_number = None
            self.last_simulation_time = None
            self.error_message = None
            self.error_module = None

    @property
    def stdout_file_path(self):
        if self._stdout_file_path is None:
            self._stdout_file_path = self.task._resolve_output_file_path("cmdenv-output-file")
        return self._stdout_file_path

    @stdout_file_path.setter
    def stdout_file_path(self, value):
        self._stdout_file_path = value

    @property
    def eventlog_file_path(self):
        if self._eventlog_file_path is None:
            self._eventlog_file_path = self.task._resolve_output_file_path("eventlog-file")
        return self._eventlog_file_path

    @eventlog_file_path.setter
    def eventlog_file_path(self, value):
        self._eventlog_file_path = value

    @property
    def scalar_file_path(self):
        if self._scalar_file_path is None:
            self._scalar_file_path = self.task._resolve_output_file_path("output-scalar-file")
        return self._scalar_file_path

    @scalar_file_path.setter
    def scalar_file_path(self, value):
        self._scalar_file_path = value

    @property
    def vector_file_path(self):
        if self._vector_file_path is None:
            self._vector_file_path = self.task._resolve_output_file_path("output-vector-file")
        return self._vector_file_path

    @vector_file_path.setter
    def vector_file_path(self, value):
        self._vector_file_path = value

    def get_error_message(self, complete_error_message=True, **kwargs):
        if complete_error_message and self.error_module and self.error_message:
            return self.error_message + " -- in module " + self.error_module
        else:
            return self.error_message or ""

    def _get_full_result_path(self, relative_path):
        simulation_config = self.task.simulation_config
        simulation_project = simulation_config.simulation_project
        return simulation_project.get_full_path(os.path.join(simulation_config.working_directory, relative_path))

    def get_scalars(self, include_fields=True, include_runattrs=False, **kwargs):
        """
        Returns scalar results from the simulation's ``.sca`` file as a DataFrame.

        Parameters:
            include_fields (bool): Include statistic fields (count, mean, etc.) as scalars.
            include_runattrs (bool): Include run attributes in the returned DataFrame.

        Returns (DataFrame):
            A pandas DataFrame with the scalar results.
        """
        path = self._get_full_result_path(self.scalar_file_path)
        df = read_result_files(path, include_fields_as_scalars=include_fields, **kwargs)
        return _get_scalars(df, include_runattrs=include_runattrs)

    def get_vectors(self, include_runattrs=False, **kwargs):
        """
        Returns vector results from the simulation's ``.vec`` file as a DataFrame.

        Parameters:
            include_runattrs (bool): Include run attributes in the returned DataFrame.

        Returns (DataFrame):
            A pandas DataFrame with the vector results.
        """
        path = self._get_full_result_path(self.vector_file_path)
        df = read_result_files(path, **kwargs)
        return _get_vectors(df, include_runattrs=include_runattrs)

    def get_histograms(self, include_runattrs=False, **kwargs):
        """
        Returns histogram results from the simulation's ``.sca`` file as a DataFrame.

        Parameters:
            include_runattrs (bool): Include run attributes in the returned DataFrame.

        Returns (DataFrame):
            A pandas DataFrame with the histogram results.
        """
        path = self._get_full_result_path(self.scalar_file_path)
        df = read_result_files(path, **kwargs)
        return _get_histograms(df, include_runattrs=include_runattrs)

    def get_subprocess_result(self):
        return self.subprocess_result

    def get_fingerprint_trajectory(self):
        simulation_config = self.task.simulation_config
        simulation_project = simulation_config.simulation_project
        file_path = simulation_project.get_full_path(simulation_config.working_directory + "/" + self.eventlog_file_path)
        eventlog_file = open(file_path)
        fingerprints = []
        event_numbers = []
        ingredients = None
        pattern = re.compile(r"E # (\d+) .* f (.*?)/(.*)")
        for line in eventlog_file:
            match = pattern.match(line)
            if match:
                ingredients = match.group(3)
                fingerprints.append(Fingerprint(match.group(2), match.group(3)))
                event_numbers.append(int(match.group(1)))
        eventlog_file.close()
        return FingerprintTrajectory(self, ingredients, fingerprints, event_numbers)

    def get_stdout_trajectory(self, filter=None, exclude_filter=None, full_match=False):
        simulation_config = self.task.simulation_config
        simulation_project = simulation_config.simulation_project
        file_path = simulation_project.get_full_path(simulation_config.working_directory + "/" + self.stdout_file_path)
        stdout_file = open(file_path)
        event_numbers = []
        lines = []
        event_number = None
        pattern = re.compile(r"\*\* Event #(\d+) .*")
        for line in stdout_file:
            match = pattern.match(line)
            if match:
                event_number = int(match.group(1))
            elif event_number is not None:
                if matches_filter(line, filter, exclude_filter, full_match):
                    event_numbers.append(event_number)
                    lines.append(line)
        stdout_file.close()
        return StdoutTrajectory(self, event_numbers, lines)

class SimulationTask(Task):
    """
    Represents a simulation task that can be run as a separate process or in the process where Python is running.

    Please note that undocumented features are not supposed to be called by the user.
    """

    def __init__(self, simulation_config=None, run_number=0, inifile_entries=[], itervars=None, mode="release", debug=None, remove_launch=True, break_at_event_number=None, break_at_matching_event=None, user_interface="Cmdenv", result_folder="results", sim_time_limit=None, cpu_time_limit=None, record_eventlog=None, record_pcap=None, stdout_file_path=None, eventlog_file_path=None, scalar_file_path=None, vector_file_path=None, wait=True, name="simulation", task_result_class=SimulationTaskResult, **kwargs):
        """
        Parameters:
            simulation_config (:py:class:`SimulationConfig <opp_repl.simulation.config.SimulationConfig>`):
                The simulation config that is used to run this simulation task.

            run_number (number):
                The number uniquely identifying the simulation run.

            inifile_entries (list):
                A list of additional inifile entries.

            itervars (string):
                The list of iteration variables.

            mode (string):
                The build mode that is used to run this simulation task. Valid values are "release", "debug", and "sanitize".

            debug (bool):
                Specifies that the IDE debugger should be attached to the running simulation.

            remove_launch (bool):
                Specifies if the IDE should remove the launch after the simulation terminates.

            break_at_event_number (int):
                Specifies an event number at which a breakpoint is to be set.

            break_at_matching_event (string):
                Specifies a C++ expression at which a breakpoint is to be set.

            user_interface (string):
                The user interface that is used to run this simulation task. Valid values are "Cmdenv", and "Qtenv".

            result_folder (string):
                The result folder where the output files are generated.

            sim_time_limit (string):
                The simulation time limit as quantity with unit (e.g. "1s").

            cpu_time_limit (string):
                The CPU time limit as quantity with unit (e.g. "1s").

            record_eventlog (bool):
                Specifies whether the eventlog file should be recorded or not.

            record_pcap (bool):
                Specifies whether PCAP files should be recorded or not.

            stdout_file_path (string):
                Overrides the relative file path of the STDOUT file, not set by default.

            eventlog_file_path (string):
                Overrides the relative file path of the eventlog file, not set by default.

            scalar_file_path (string):
                Overrides the relative file path of the scalar file, not set by default.

            vector_file_path (string):
                Overrides the relative file path of the vector file, not set by default.

            wait (bool):
                Determines if running the task waits the simulation to complete or not.

            task_result_class (type):
                The Python class that is used to return the result.

            kwargs (dict):
                Additional parameters are inherited from the :py:class:`Task <opp_repl.common.Task>` constructor.
        """
        super().__init__(name=name, task_result_class=task_result_class, **kwargs)
        assert run_number is not None
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.simulation_config = simulation_config
        self.inifile_entries = inifile_entries
        self.interactive = None # NOTE delayed to is_interactive()
        self.run_number = run_number
        self.itervars = itervars
        self.mode = mode
        self.debug = debug or (True if break_at_event_number is not None or break_at_matching_event is not None else False)
        self.remove_launch = remove_launch
        self.break_at_event_number = break_at_event_number
        self.break_at_matching_event = break_at_matching_event
        self.user_interface = user_interface
        self.result_folder = result_folder
        self.sim_time_limit = sim_time_limit
        self.cpu_time_limit = cpu_time_limit
        self.record_eventlog = record_eventlog
        self.record_pcap = record_pcap
        self.stdout_file_path = stdout_file_path
        self.eventlog_file_path = eventlog_file_path
        self.scalar_file_path = scalar_file_path
        self.vector_file_path = vector_file_path
        self.wait = wait
        # self.dependency_source_file_paths = None

    def get_hash(self, complete=True, binary=True, **kwargs):
        hasher = hashlib.sha256()
        if complete:
            hasher.update(self.simulation_config.simulation_project.get_hash(binary=binary, **kwargs))
        else:
            if binary:
                raise Exception("Not implemented yet")
            else:
                return None
                # if self.dependency_source_file_paths:
                #     for file_path in self.dependency_source_file_paths:
                #         hasher.update(open(file_path, "rb").read())
                # else:
                #     return None
        hasher.update(self.simulation_config.get_hash(**kwargs))
        hasher.update(str(self.run_number).encode("utf-8"))
        hasher.update(self.mode.encode("utf-8"))
        if self.sim_time_limit:
            hasher.update(self.sim_time_limit.encode("utf-8"))
        return hasher.digest()

    def get_result_folder_full_path(self):
        return self.simulation_config.simulation_project.get_full_path(os.path.join(self.simulation_config.working_directory, self.result_folder))

    def clear_result_folder(self):
        path = self.get_result_folder_full_path()
        if os.path.exists(path):
            for suffix in ["sca", "vec", "vci", "elog", "log", "rt"]:
                for file_name in glob.glob(os.path.join(path, "*." + suffix)):
                    os.remove(file_name)

    def remove_result_folder(self):
        path = self.get_result_folder_full_path()
        self.clear_result_folder()
        if os.path.exists(path):
            os.rmdir(path)

    # TODO replace this with something more efficient?
    def is_interactive(self):
        if self.interactive is None:
            simulation_config = self.simulation_config
            simulation_project = simulation_config.simulation_project
            executable = simulation_project.get_executable()
            default_args = simulation_project.get_default_args()
            args = [executable, *default_args, "-s", "-u", "Cmdenv", "-f", simulation_config.ini_file, "-c", simulation_config.config, "-r", "0", "--sim-time-limit", "0s"]
            if simulation_project.opp_env_workspace:
                subprocess_result = OppEnvSimulationRunner().run_args(simulation_project, args, cwd=simulation_project.get_full_path(simulation_config.working_directory))
            else:
                subprocess_result = run_command_with_logging(args, cwd=simulation_project.get_full_path(simulation_config.working_directory), env=simulation_project.get_env())
            match = re.search(r"The simulation wanted to ask a question|The simulation attempted to prompt for user input", subprocess_result.stderr)
            self.interactive = match is not None
        return self.interactive

    def _resolve_output_file_path(self, option_name):
        file_path_attr = {
            "cmdenv-output-file": "stdout_file_path",
            "eventlog-file": "eventlog_file_path",
            "output-scalar-file": "scalar_file_path",
            "output-vector-file": "vector_file_path",
        }[option_name]
        explicit_path = getattr(self, file_path_attr)
        if explicit_path:
            return explicit_path
        simulation_config = self.simulation_config
        simulation_project = simulation_config.simulation_project
        executable = simulation_project.get_executable()
        default_args = simulation_project.get_default_args()
        inifile_entries_args = list(map(lambda inifile_entry: "--" + inifile_entry, self.inifile_entries))
        result_folder_args = ["--result-dir", self.result_folder] if self.result_folder != "results" else []
        args = [executable, *default_args, "-s", "-f", simulation_config.ini_file, "-c", simulation_config.config, "-r", str(self.run_number), *inifile_entries_args, *result_folder_args, "-e", option_name]
        if simulation_project.opp_env_workspace:
            subprocess_result = OppEnvSimulationRunner().run_args(simulation_project, args, cwd=simulation_project.get_full_path(simulation_config.working_directory))
        else:
            subprocess_result = run_command_with_logging(args, cwd=simulation_project.get_full_path(simulation_config.working_directory), env=simulation_project.get_env())
        return subprocess_result.stdout.strip().strip('"')

    def get_expected_result(self):
        return self.simulation_config.expected_result

    def get_parameters_string(self, **kwargs):
        working_directory = self.simulation_config.working_directory
        ini_file = self.simulation_config.ini_file
        config = self.simulation_config.config
        return working_directory + \
               (" -f " + ini_file if ini_file != "omnetpp.ini" else "") + \
               (" -c " + config if config != "General" else "") + \
               (" -r " + str(self.run_number) if self.run_number != 0 else "") + \
               (" for " + self.sim_time_limit if self.sim_time_limit else "")

    def get_sim_time_limit(self):
        return self.sim_time_limit(self.simulation_config, self.run_number) if callable(self.sim_time_limit) else self.sim_time_limit

    def get_cpu_time_limit(self):
        return self.cpu_time_limit(self.simulation_config, self.run_number) if callable(self.cpu_time_limit) else self.cpu_time_limit

    def run(self, **kwargs):
        """
        Runs a simulation task by running the simulation as a child process or in the same process where Python is running.

        Parameters:
            append_args (list):
                Additional command line arguments for the simulation executable.

            simulation_runner (string):
                Determines if the simulation is run as a separate process or in the same process where Python is running.
                Valid values are "subprocess" and "inprocess".

            simulation_runner_class (type):
                The simulation runner class that is used to run the simulation. If not specified, then this is determined
                by the simulation_runner parameter.

        Returns (SimulationTaskResult):
            a simulation task result that contains the several simulation specific information and also the subprocess
            result if applicable.
        """
        return super().run(**kwargs)

    def run_protected(self, prepend_args=[], append_args=[],  simulation_runner=None, simulation_runner_class=None, **kwargs):
        simulation_project = self.simulation_config.simulation_project
        working_directory = self.simulation_config.working_directory
        ini_file = self.simulation_config.ini_file
        config = self.simulation_config.config
        inifile_entries_args = list(map(lambda inifile_entry: "--" + inifile_entry, self.inifile_entries))
        result_folder_args = ["--result-dir", self.result_folder] if self.result_folder != "results" else []
        sim_time_limit_args = ["--sim-time-limit", self.get_sim_time_limit()] if self.sim_time_limit else []
        cpu_time_limit_args = ["--cpu-time-limit", self.get_cpu_time_limit()] if self.cpu_time_limit else []
        record_eventlog_args = ["--record-eventlog", "true"] if self.record_eventlog else []
        file_args = (["--cmdenv-output-file=" + self.stdout_file_path] if self.stdout_file_path else []) + \
                    (["--eventlog-file=" + self.eventlog_file_path] if self.eventlog_file_path else []) + \
                    (["--output-scalar-file=" + self.scalar_file_path] if self.scalar_file_path else []) + \
                    (["--output-vector-file=" + self.vector_file_path] if self.vector_file_path else [])
        record_pcap_args = ["--**.numPcapRecorders=1", "--**.checksumMode=\"computed\"", "--**.fcsMode=\"computed\""] if self.record_pcap else []
        executable = simulation_project.get_executable(mode=self.mode)
        default_args = simulation_project.get_default_args()
        args = [*prepend_args, executable, *default_args, "-s", "-u", self.user_interface, "-f", ini_file, "-c", config, "-r", str(self.run_number), *inifile_entries_args, *result_folder_args, *sim_time_limit_args, *cpu_time_limit_args, *record_eventlog_args, *file_args, *record_pcap_args, *append_args]
        expected_result = self.get_expected_result()
        if simulation_runner is None:
            if self.debug:
                simulation_runner = "ide"
            elif simulation_project.opp_env_workspace:
                simulation_runner = "opp_env"
            else:
                simulation_runner = "subprocess"
        if simulation_runner_class is None:
            if simulation_runner == "subprocess":
                simulation_runner_class = SubprocessSimulationRunner
            elif simulation_runner == "opp_env":
                simulation_runner_class = OppEnvSimulationRunner
            elif simulation_runner == "inprocess":
                import opp_repl.cffi
                simulation_runner_class = opp_repl.cffi.InprocessSimulationRunner
            elif simulation_runner == "ide":
                simulation_runner_class = IdeSimulationRunner
            else:
                raise Exception("Unknown simulation_runner")
        subprocess_result = simulation_runner_class().run(self, args)
        if subprocess_result.returncode == signal.SIGINT.value or subprocess_result.returncode == -signal.SIGINT.value:
            task_result = self.task_result_class(task=self, subprocess_result=subprocess_result, result="CANCEL", expected_result=expected_result, reason="Cancel by user")
        elif subprocess_result.returncode == 0:
            task_result = self.task_result_class(task=self, subprocess_result=subprocess_result, result="DONE", expected_result=expected_result)
        else:
            if subprocess_result.returncode == 127:
                reason = "Executable not found (exit code 127). Was the project built? Does the binary name match the project name?"
            else:
                reason = f"Non-zero exit code: {subprocess_result.returncode}"
            task_result = self.task_result_class(task=self, subprocess_result=subprocess_result, result="ERROR", expected_result=expected_result, reason=reason)
        # self.dependency_source_file_paths = self.collect_dependency_source_file_paths(task_result)
        task_result.partial_source_hash = hex_or_none(self.get_hash(complete=False, binary=False))
        return task_result

    # def collect_dependency_source_file_paths(self, simulation_task_result):
    #     simulation_project = self.simulation_config.simulation_project
    #     stdout = simulation_task_result.subprocess_result.stdout
    #     ini_dependency_file_paths = []
    #     ned_dependency_file_paths = []
    #     cpp_dependency_file_paths = []
    #     for line in stdout.splitlines():
    #         match = re.match(r"INI dependency: (.*)", line)
    #         if match:
    #             ini_full_path = simulation_project.get_full_path(os.path.join(self.simulation_config.working_directory, match.group(1)))
    #             if not ini_full_path in ini_dependency_file_paths:
    #                 ini_dependency_file_paths.append(ini_full_path)
    #         match = re.match(r"NED dependency: (.*)", line)
    #         if match:
    #             ned_full_path = match.group(1)
    #             if os.path.exists(ned_full_path):
    #                 if not ned_full_path in ned_dependency_file_paths:
    #                     ned_dependency_file_paths.append(ned_full_path)
    #         match = re.match(r"CC dependency: (.*)", line)
    #         if match:
    #             cpp_full_path = match.group(1)
    #             if not cpp_full_path in cpp_dependency_file_paths:
    #                 cpp_dependency_file_paths.append(cpp_full_path)
    #     cpp_dependency_file_paths = self.collect_cpp_dependency_file_paths(cpp_dependency_file_paths)
    #     msg_dependency_file_paths = [file_name.replace("_m.cc", ".msg") for file_name in cpp_dependency_file_paths if file_name.endswith("_m.cc")]
    #     return sorted(ini_dependency_file_paths + ned_dependency_file_paths + msg_dependency_file_paths + cpp_dependency_file_paths)

    # def collect_cpp_dependency_file_paths(self, file_names):
    #     simulation_project = self.simulation_config.simulation_project
    #     while True:
    #         file_names_copy = file_names.copy()
    #         for file_name in file_names_copy:
    #             full_file_path = simulation_project.get_full_path(f"out/clang-{self.mode}/" + re.sub(r".cc", ".o.d", file_name))
    #             if os.path.exists(full_file_path):
    #                 dependency = read_dependency_file(full_file_path)
    #                 for key, depends_on_file_names in dependency.items():
    #                     additional_file_names = [file_name.replace(".h", ".cc") for file_name in depends_on_file_names if file_name.endswith(".h")]
    #                     file_names = file_names + depends_on_file_names + additional_file_names
    #         file_names = sorted(list(set(file_names)))
    #         if file_names_copy == file_names:
    #             break
    #     file_names = [simulation_project.get_full_path(file_name) for file_name in file_names]
    #     return sorted([file_name for file_name in file_names if os.path.exists(file_name)])

class MultipleSimulationTaskResults(MultipleTaskResults):
    """
    Represents multiple simulation task results with convenience methods
    for reading merged result data across all runs.
    """

    def get_scalars(self, **kwargs):
        """
        Returns scalar results from all simulation runs merged into a single DataFrame.

        Parameters:
            kwargs: Additional parameters passed to each :py:meth:`SimulationTaskResult.get_scalars`.

        Returns (DataFrame):
            A pandas DataFrame with the merged scalar results.
        """
        return pd.concat([r.get_scalars(**kwargs) for r in self.results if r.result == "DONE"], ignore_index=True)

    def get_vectors(self, **kwargs):
        """
        Returns vector results from all simulation runs merged into a single DataFrame.

        Parameters:
            kwargs: Additional parameters passed to each :py:meth:`SimulationTaskResult.get_vectors`.

        Returns (DataFrame):
            A pandas DataFrame with the merged vector results.
        """
        return pd.concat([r.get_vectors(**kwargs) for r in self.results if r.result == "DONE"], ignore_index=True)

    def get_histograms(self, **kwargs):
        """
        Returns histogram results from all simulation runs merged into a single DataFrame.

        Parameters:
            kwargs: Additional parameters passed to each :py:meth:`SimulationTaskResult.get_histograms`.

        Returns (DataFrame):
            A pandas DataFrame with the merged histogram results.
        """
        return pd.concat([r.get_histograms(**kwargs) for r in self.results if r.result == "DONE"], ignore_index=True)

class MultipleSimulationTasks(MultipleTasks):
    """
    Represents multiple simulation tasks that can be run together.
    """
    def __init__(self, simulation_project=None, mode="release", build=None, name="simulation", multiple_task_results_class=MultipleSimulationTaskResults, **kwargs):
        """
        Initializes a new multiple simulation tasks object.

        Parameters:
            mode (string):
                Specifies the build mode for running. Valid values are "debug", "release", and "sanitize".

            build (bool):
                Determines if the simulation project is built before running any simulation.

            kwargs (dict):
                Additional arguments are inherited from :py:class:`MultipleTasks <opp_repl.common.task.MultipleTasks>` constructor.
        """
        super().__init__(name=name, multiple_task_results_class=multiple_task_results_class, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.mode = mode
        self.build = build if build is not None else get_default_build_argument()
        self.simulation_project = simulation_project

    def run(self, **kwargs):
        """
        Runs multiple simulation tasks.

        Parameters:
            kwargs (dict):
                Additional parameters are inherited from the :py:func:`build_project <opp_repl.simulation.build.build_project>` function
                and also from the :py:meth:`run <opp_repl.common.task.MultipleTasks.run>` method.

        Returns (MultipleTaskResults):
            An object that contains a list of :py:class:`SimulationTask`.
        """
        return super().run(**kwargs)

    def build_before_run(self, **kwargs):
        self.simulation_project.build(mode=self.mode)

    def run_protected(self, **kwargs):
        if self.build:
            self.build_before_run(**kwargs)
        return super().run_protected(**kwargs)

    def get_parameters_string(self, **kwargs):
        return ""

def get_simulation_tasks(simulation_project=None, simulation_configs=None, mode=None, debug=None, break_at_event_number=None, break_at_matching_event=None, run_number=None, run_number_filter=None, exclude_run_number_filter=None, sim_time_limit=None, cpu_time_limit=None, concurrent=True, expected_num_tasks=None, simulation_task_class=SimulationTask, multiple_simulation_tasks_class=MultipleSimulationTasks, affected_by_modification_filter=None, **kwargs):
    """
    Returns multiple simulation tasks matching the filter criteria. The returned tasks can be run by calling the
    :py:meth:`run <opp_repl.common.task.MultipleTasks.run>` method.

    Parameters:
        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>` or None):
            The simulation project from which simulation tasks are collected. If not specified then the default simulation
            project is used.

        simulation_configs (List of :py:class:`SimulationConfig <opp_repl.simulation.config.SimulationConfig>` or None):
            The list of simulation configurations from which the simulation tasks are collected. If not specified then
            all simulation configurations are used.

        mode (string):
            Determines the build mode for the simulation project before running any of the returned simulation tasks.
            Valid values are "debug" and "release".

        debug (bool):
            Specifies that the IDE debugger should be attached to the running simulation.

        break_at_event_number (int):
            Specifies an event number at which a breakpoint is to be set.

        break_at_matching_event (string):
            Specifies a C++ expression at which a breakpoint is to be set.

        run_number (int or None):
            The simulation run number of all returned simulation tasks. If not specified, then this filter criteria is
            ignored.

        run_number_filter (string or None):
            A regular expression that matches the simulation run number of the returned simulation tasks. If not specified,
            then this filter criteria is ignored.

        exclude_run_number_filter (string or None):
            A regular expression that does not match the simulation run number of the returned simulation tasks. If not
            specified, then this filter criteria is ignored.

        sim_time_limit (string or None):
            The simulation time limit of the returned simulation tasks. If not specified, then the value in the simulation
            configuration is used.

        cpu_time_limit (string or None):
            The CPU processing time limit of the returned simulation tasks. If not specified, then the value in the
            simulation configuration is used.

        concurrent (bool):
            Specifies if collecting simulation configurations and simulation tasks is done sequentially or concurrently.

        expected_num_tasks (int):
            The number of tasks that is expected to be returned. If the result doesn't match an exception is raised.

        simulation_task_class (type):
            Determines the Python class of the returned simulation task objects.

        multiple_simulation_tasks_class (type):
            Determines the Python class of the returned multiple simulation tasks object.

        affected_by_modification_filter (list of strings, string, or None):
            Filters simulation configs to only those affected by the given modifications.
            Uses the project's SimulationTaskDependencyStore (must be built first via
            update_simulation_task_dependencies()). Type-based dispatch:
            - list of strings: file paths relative to project root
            - string containing '..': git commit range (e.g. 'master..HEAD')
            - string without '..': single git commit hash

        kwargs (dict):
            Additional parameters are inherited from the :py:meth:`matches_filter <opp_repl.simulation.config.SimulationConfig.matches_filter>`
            method  and also from the :py:class:`SimulationTask` and :py:class:`MultipleSimulationTasks` constructors.

    Returns (:py:class:`MultipleSimulationTasks`):
        An object that contains a list of :py:class:`SimulationTask` matching the filter criteria. Each simulation task
        describes a simulation that can be run (and re-run) without providing additional parameters.
    """
    if debug is None:
        debug = True if break_at_event_number or break_at_matching_event else False
    if mode is None:
        mode = "debug" if debug else "release"
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    if simulation_configs is None:
        simulation_configs = simulation_project.get_simulation_configs(concurrent=concurrent, **kwargs)
    if affected_by_modification_filter is not None:
        from opp_repl.simulation.dependency import get_simulation_task_dependency_store
        store = get_simulation_task_dependency_store(simulation_project)
        if isinstance(affected_by_modification_filter, list):
            modified_files = affected_by_modification_filter
        elif isinstance(affected_by_modification_filter, str) and ".." in affected_by_modification_filter:
            from_commit, to_commit = affected_by_modification_filter.split("..", 1)
            modified_files = store.get_modified_files_for_git_range(from_commit, to_commit)
        elif isinstance(affected_by_modification_filter, str):
            modified_files = store.get_modified_files_for_git_commit(affected_by_modification_filter)
        else:
            raise ValueError(f"Invalid affected_by_modification_filter type: {type(affected_by_modification_filter)}")
        affected_keys = store.get_affected_simulation_config_keys(modified_files)
        if affected_keys is not None:
            simulation_configs = [c for c in simulation_configs if (c.working_directory, c.ini_file, c.config) in affected_keys]
    simulation_tasks = _collect_simulation_tasks_for_project(simulation_configs, run_number=run_number, run_number_filter=run_number_filter, exclude_run_number_filter=exclude_run_number_filter, sim_time_limit=sim_time_limit, cpu_time_limit=cpu_time_limit, mode=mode, debug=debug, break_at_event_number=break_at_event_number, break_at_matching_event=break_at_matching_event, simulation_task_class=simulation_task_class, **kwargs)
    if expected_num_tasks is not None and len(simulation_tasks) != expected_num_tasks:
        raise Exception("Number of found and expected simulation tasks mismatch")
    return multiple_simulation_tasks_class(tasks=simulation_tasks, simulation_project=simulation_project, mode=mode, concurrent=concurrent, **kwargs)
get_simulation_tasks.__signature__ = combine_signatures(get_simulation_tasks, SimulationConfig.matches_filter, SimulationTask.__init__, MultipleSimulationTasks.__init__)

def _collect_simulation_tasks_for_project(simulation_configs, run_number=None, run_number_filter=None, exclude_run_number_filter=None, sim_time_limit=None, cpu_time_limit=None, mode="release", debug=False, break_at_event_number=None, break_at_matching_event=None, simulation_task_class=SimulationTask, **kwargs):
    simulation_tasks = []
    for simulation_config in simulation_configs:
        if run_number is not None:
            simulation_run_sim_time_limit = sim_time_limit(simulation_config, run_number) if callable(sim_time_limit) else (sim_time_limit or simulation_config.sim_time_limit)
            simulation_task = simulation_task_class(simulation_config=simulation_config, run_number=run_number, mode=mode, debug=debug, break_at_event_number=break_at_event_number, break_at_matching_event=break_at_matching_event, sim_time_limit=simulation_run_sim_time_limit, cpu_time_limit=cpu_time_limit, **kwargs)
            simulation_tasks.append(simulation_task)
        else:
            for generated_run_number in range(0, simulation_config.num_runs):
                if matches_filter(str(generated_run_number), run_number_filter, exclude_run_number_filter, True):
                    simulation_run_sim_time_limit = sim_time_limit(simulation_config, generated_run_number) if callable(sim_time_limit) else (sim_time_limit or simulation_config.sim_time_limit)
                    simulation_task = simulation_task_class(simulation_config=simulation_config, run_number=generated_run_number, mode=mode, debug=debug, break_at_event_number=break_at_event_number, break_at_matching_event=break_at_matching_event, sim_time_limit=simulation_run_sim_time_limit, cpu_time_limit=cpu_time_limit, **kwargs)
                    simulation_tasks.append(simulation_task)
    return simulation_tasks

def get_simulation_task(**kwargs):
    multiple_simulation_tasks = get_simulation_tasks(**kwargs)
    num_tasks = len(multiple_simulation_tasks.tasks)
    if num_tasks != 1:
        raise Exception(f"Found {num_tasks} simulation tasks instead of one")
    return multiple_simulation_tasks.tasks[0]
get_simulation_task.__signature__ = combine_signatures(get_simulation_task, get_simulation_tasks)

def run_simulations(**kwargs):
    """
    Runs one or more simulations that match the provided filter criteria. The simulations can be run sequentially or
    concurrently on a single computer or on an SSH cluster. Besides, the simulations can be run as separate processes
    and also in the same Python process loading the required libraries.

    Parameters:
        kwargs (dict):
            Additional parameters are inherited from the :py:func:`get_simulation_tasks` function and also from the
            :py:meth:`MultipleSimulationTasks.run` method.

    Returns (:py:class:`MultipleTaskResults <opp_repl.common.task.MultipleTaskResults>`):
        an object that contains a list of :py:class:`SimulationTaskResult` objects. Each object describes the results
        of running one simulation.
    """
    multiple_simulation_tasks = get_simulation_tasks(**kwargs)
    return multiple_simulation_tasks.run(**kwargs)
run_simulations.__signature__ = combine_signatures(run_simulations, get_simulation_tasks, MultipleSimulationTasks.run)

def clean_simulation_results(simulation_project=None, simulation_configs=None, **kwargs):
    """
    Cleans the results folders for the simulation configs matching the provided filter criteria.

    Parameters:
        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>` or None):
            The simulation project from which simulation tasks are collected. If not specified then the default simulation
            project is used.

        simulation_configs (List of :py:class:`SimulationConfig <opp_repl.simulation.config.SimulationConfig>` or None):
            The list of simulation configurations from which the simulation tasks are collected. If not specified then
            all simulation configurations are used.

        kwargs (dict): Additional parameters are inherited from the :py:meth:`get_simulation_configs <opp_repl.simulation.project.SimulationProject.get_simulation_configs>`
            function.

    Returns (None):
        nothing.
    """
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    if simulation_configs is None:
        simulation_configs = simulation_project.get_simulation_configs(**kwargs)
    for simulation_config in simulation_configs:
        simulation_config.clean_simulation_results()
clean_simulation_results.__signature__ = combine_signatures(clean_simulation_results, SimulationConfig.matches_filter)
