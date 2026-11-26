"""
The records of the test map. In a coverage build, a simulation runner gives each run its own
profile, a file trace and the list of its NED types, and after the run it writes a record of the
run into a records folder. The map writer reads the records. See the test selection plan of
opp_repl (``plan/pending/test-selection.md``, section 8.1).

A record is the folder ``<records folder>/<run id>`` with these files:

- ``run.json``: the key and the parameters of the run, its exit code and end, its NED types and
  the section chain of its config. The runner writes it last, so a record without it is not
  complete.
- ``functions.txt.gz``: the mangled names of the functions that ran (an entry count above zero).
- ``files.txt``: ``<kind> <path>`` for each project file that the run used, with the path relative
  to the project root. The kinds are ``read``, ``examined``, ``listed`` and ``lookup`` (a failed
  lookup of a path).

The profile of the run goes into the profile pool of the project as ``<run id>.profdata``, so that
the coverage export of the suite gives the same counts as without the records.
"""

import functools
import glob
import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time

from opp_repl.common.util import run_command_with_logging

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

TEST_MAP_RECORD_VERSION = 1

def get_test_map_run_key(kind, simulation_task):
    """
    Returns the key of a run: the kind of the test, the ini file, the config, the run number and the
    sim time limit, for example ``fingerprint:examples/adhoc/hostautoconf/omnetpp.ini:General:#0:100s``.
    The tests of one fingerprint group share one run, so the key has no ingredients.
    """
    simulation_config = simulation_task.simulation_config
    ini_path = os.path.normpath(os.path.join(simulation_config.working_directory, simulation_config.ini_file))
    return f"{kind}:{ini_path}:{simulation_config.config}:#{simulation_task.run_number}:{simulation_task.get_sim_time_limit() or ''}"

def get_test_map_run_id(run_key):
    """Returns the short id of a run: the first 10 hex digits of the SHA-1 of its key. The id stays the same from map to map."""
    return hashlib.sha1(run_key.encode("utf-8")).hexdigest()[:10]

def read_functions_that_ran(show_output):
    """Returns the names of the functions with an entry count above zero in the output of ``llvm-profdata show --all-functions``."""
    names = []
    name = None
    for line in show_output.splitlines():
        if line.startswith("  ") and not line.startswith("   ") and line.endswith(":"):
            name = line[2:-1]
        elif name is not None and line.startswith("    Function count: "):
            if int(line.split(":", 1)[1]) > 0:
                names.append(name)
            name = None
    return names

_NED_TYPE_PREFIX = "instantiated NED type: "

def read_instantiated_ned_types(stdout):
    """Returns the sorted NED types that ``--print-instantiated-ned-types=true`` printed."""
    return sorted({line[len(_NED_TYPE_PREFIX):].strip() for line in stdout.splitlines() if line.startswith(_NED_TYPE_PREFIX)})

def read_end_of_run(stdout):
    """
    Returns the end of a run from its Cmdenv output: the text of the last ``<!>`` line that gives an
    event number (the stop or the error), else of the last ``<!>`` line, and the event number and the
    simulation time in it. Each value is None if the output does not give it. The fingerprint lines
    (``<!> Fingerprint ...``) come after the stop line, and they give no event number.
    """
    lines = [line.strip()[3:].strip() for line in stdout.splitlines() if line.startswith("<!>")]
    stop_lines = [line for line in lines if re.search(r"event #\d+", line)]
    text = stop_lines[-1] if stop_lines else lines[-1] if lines else None
    event = re.search(r"event #(\d+)", text) if text else None
    sim_time = re.search(r"\bt=([^\s,]+)", text) if text else None
    return {"text": text, "event": int(event.group(1)) if event else None, "sim_time": sim_time.group(1) if sim_time else None}

def read_section_chain(query_output):
    """Returns the sections of the output of ``-q sectioninheritance``: ``Config X`` or ``General``, one on each line."""
    return [line.strip() for line in query_output.splitlines() if re.match(r"\s*(Config \S+|General)\s*$", line)]

def reduce_file_trace(lines, root_folder, output_folders=[]):
    """
    Reduces the lines of a file trace (see ``filetrace.c``) to the project files that the run used:
    a sorted list of ``(kind, path)`` with the path relative to *root_folder* (a real path).
    The outputs of the run are left out: an open that only writes (``write``), and any path in one of
    *output_folders* (relative to the root, for example the result folder of the run).

    - ``read``: an open of an existing file. ``listed``: a directory that the process listed.
      ``examined``: a ``stat`` or ``access`` of an existing path. ``lookup``: any operation on a path
      that does not exist.
    - The NED folder walk of omnetpp is left out: it lists each folder of the NED path with
      ``glob("*")`` and examines each entry. So the successful examinations in a walked folder and
      the reads of ``.ned`` files are not recorded; the NED rules of the selection cover them.
    - A failed lookup of a broken link (for example ``doc/media`` without the media checkout) is
      left out. A path outside the root, a path in ``out/`` (the build), and an operation relative
      to a directory file descriptor are left out.
    """
    root = os.path.join(root_folder, "")
    output_prefixes = tuple(os.path.join(os.path.normpath(folder), "") for folder in output_folders)
    walked = set()
    entries = []
    for line in lines:
        parts = line.rstrip("\n").split(" ", 2)
        if len(parts) != 3:
            continue
        op, status, path = parts
        if op in ("openat", "statat", "chdir", "write"):
            continue
        path = os.path.normpath(path)
        if op == "glob":
            walked.add(os.path.dirname(path))
        else:
            entries.append((op, status == "ok", path))
    result = set()
    real_paths = {}
    for op, ok, path in entries:
        if ok:
            if op in ("stat", "access") and os.path.dirname(path) in walked:
                continue
            kind = "listed" if op == "list" else "read" if op == "open" else "examined"
        else:
            if os.path.islink(path):
                continue
            kind = "lookup"
        real_path = real_paths.get(path)
        if real_path is None:
            real_path = real_paths[path] = os.path.realpath(path)
        if real_path == root_folder:
            relative_path = "."
        elif real_path.startswith(root):
            relative_path = real_path[len(root):]
        else:
            continue
        if relative_path.startswith("out/") or (relative_path + "/").startswith(output_prefixes) or (kind == "read" and relative_path.endswith(".ned")):
            continue
        result.add((kind, relative_path))
    return sorted(result)

def build_file_trace_library(folder):
    """Compiles ``filetrace.c`` into ``<folder>/libopp_repl_filetrace.so`` if the library is missing or older than the source, and returns its path."""
    source = os.path.join(os.path.dirname(os.path.abspath(__file__)), "filetrace.c")
    library = os.path.join(folder, "libopp_repl_filetrace.so")
    if not os.path.exists(library) or os.path.getmtime(library) < os.path.getmtime(source):
        os.makedirs(folder, exist_ok=True)
        temporary = f"{library}.{os.getpid()}.tmp"
        args = [os.environ.get("CC", "cc"), "-O2", "-shared", "-fPIC", "-o", temporary, source, "-ldl"]
        run_command_with_logging(args, error_message="Compiling the file trace library of the test map failed", command_line_logger=_logger)
        os.replace(temporary, library)
    return library

class TestMapRecorder:
    """
    Writes the record of one run of a test (see the module documentation): give the processes of the
    run the environment of :py:meth:`get_env`, and call :py:meth:`write` after the run. A coverage
    build of the run writes the profile; each process writes its own profile and file trace.
    """
    def __init__(self, records_folder, kind, trace_library, key, simulation_project, mode):
        self.kind = kind
        self.trace_library = trace_library
        self.key = key
        self.id = get_test_map_run_id(key)
        self.simulation_project = simulation_project
        self.mode = mode
        self.folder = os.path.join(records_folder, self.id)
        shutil.rmtree(self.folder, ignore_errors=True)
        self.raw_profile_folder = os.path.join(self.folder, "profraw")
        os.makedirs(self.raw_profile_folder)
        self.start_time = time.time()

    def get_env(self, env):
        """Returns *env* with the variables of the profile and of the file trace of the run."""
        env = dict(env)
        # %p: the process id; all instrumented modules of one process write into the same file
        env["LLVM_PROFILE_FILE"] = os.path.join(self.raw_profile_folder, "%p.profraw")
        env["LD_PRELOAD"] = self.trace_library + (":" + env["LD_PRELOAD"] if env.get("LD_PRELOAD") else "")
        env["OPP_REPL_FILE_TRACE"] = os.path.join(self.folder, "trace")
        return env

    def write(self, exit_code, args, output_folders=[], fields={}):
        """
        Writes the record of the run: the profile into the pool, the functions that ran, the files
        that the run used except *output_folders* (relative to the project root), and ``run.json``
        with *fields* (for example the config of a simulation).
        """
        from opp_repl.test.coverage import get_coverage_tool
        simulation_project = self.simulation_project
        elapsed_wall_time = time.time() - self.start_time
        # the profile: a sparse .profdata in the pool of the project, and the list of the functions that ran
        raw_profiles = sorted(glob.glob(os.path.join(self.raw_profile_folder, "*.profraw")))
        num_functions = None
        if raw_profiles:
            profile_folder = simulation_project.get_coverage_profile_folder()
            os.makedirs(profile_folder, exist_ok=True)
            profile = os.path.join(profile_folder, self.id + ".profdata")
            llvm_profdata = get_coverage_tool(simulation_project, "llvm-profdata", mode=self.mode)
            run_command_with_logging([llvm_profdata, "merge", "-sparse", "-o", profile, *raw_profiles], error_message="Merging the profile of a run failed", command_line_logger=_logger)
            show_output = subprocess.run([llvm_profdata, "show", "--all-functions", profile], capture_output=True, text=True, check=True).stdout
            functions = sorted(set(read_functions_that_ran(show_output)))
            num_functions = len(functions)
            with gzip.open(os.path.join(self.folder, "functions.txt.gz"), "wt") as f:
                f.write("".join(name + "\n" for name in functions))
        shutil.rmtree(self.raw_profile_folder)
        # the file trace: one file for each process of the run
        trace_files = sorted(glob.glob(os.path.join(self.folder, "trace.*")))
        trace_lines = []
        for trace_file in trace_files:
            with open(trace_file, errors="surrogateescape") as f:
                trace_lines += f.readlines()
            os.remove(trace_file)
        files = reduce_file_trace(trace_lines, os.path.realpath(simulation_project.get_full_path(".")), output_folders=output_folders)
        with open(os.path.join(self.folder, "files.txt"), "w", errors="surrogateescape") as f:
            f.write("".join(f"{kind} {path}\n" for kind, path in files))
        record = {"version": TEST_MAP_RECORD_VERSION,
                  "id": self.id,
                  "key": self.key,
                  "kind": self.kind,
                  "working_directory": None,
                  "ini_file": None,
                  "config": None,
                  "run_number": None,
                  "sim_time_limit": None,
                  "mode": self.mode,
                  "args": [*args],
                  "exit_code": exit_code,
                  "end": None,
                  "elapsed_wall_time": round(elapsed_wall_time, 3),
                  "profile": bool(raw_profiles),
                  "num_functions": num_functions,
                  "num_trace_lines": len(trace_lines),
                  "ned_types": [],
                  "sections": [],
                  **fields}
        with open(os.path.join(self.folder, "run.json"), "w") as f:
            json.dump(record, f, indent=1)
        return record

class TestMapRecorderFactory:
    """Makes the :py:class:`TestMapRecorder` of each run of the tests of *kind*; it compiles the file trace library into the records folder."""
    def __init__(self, records_folder, kind):
        self.records_folder = os.path.abspath(records_folder)
        self.kind = kind
        os.makedirs(self.records_folder, exist_ok=True)
        self.trace_library = build_file_trace_library(self.records_folder)

    def __call__(self, key, simulation_project, mode):
        return TestMapRecorder(self.records_folder, self.kind, self.trace_library, key, simulation_project, mode)

class TestMapSimulationRunner:
    """
    Runs a simulation of a coverage build as the subprocess runner does, and writes the record of the
    run (see the module documentation). Give it to the run as ``simulation_runner_class``, made by
    :py:func:`get_test_map_simulation_runner_class`.
    """
    _section_chains = {}
    _section_chains_lock = threading.Lock()

    def __init__(self, records_folder, kind, trace_library):
        self.records_folder = records_folder
        self.kind = kind
        self.trace_library = trace_library

    def run(self, simulation_task, args):
        if not simulation_task.wait:
            raise Exception("The test map needs the end of each run, so the run must wait for the simulation")
        simulation_config = simulation_task.simulation_config
        simulation_project = simulation_config.simulation_project
        working_directory = simulation_project.get_full_path(simulation_config.working_directory)
        recorder = TestMapRecorder(self.records_folder, self.kind, self.trace_library, get_test_map_run_key(self.kind, simulation_task), simulation_project, simulation_task.mode)
        env = recorder.get_env(simulation_project.get_env(mode=simulation_task.mode))
        subprocess_result = run_command_with_logging([*args, "--print-instantiated-ned-types=true"], cwd=working_directory, env=env, command_line_logger=_logger)
        result_folder = os.path.join(simulation_config.working_directory, simulation_task.result_folder)
        recorder.write(subprocess_result.returncode, args, output_folders=[result_folder],
                       fields={"working_directory": simulation_config.working_directory,
                               "ini_file": simulation_config.ini_file,
                               "config": simulation_config.config,
                               "run_number": simulation_task.run_number,
                               "sim_time_limit": simulation_task.get_sim_time_limit(),
                               "end": read_end_of_run(subprocess_result.stdout),
                               "ned_types": read_instantiated_ned_types(subprocess_result.stdout),
                               "sections": self.get_section_chain(simulation_task, working_directory)})
        return subprocess_result

    def get_section_chain(self, simulation_task, working_directory):
        """Returns the section chain of the config of the run (``-q sectioninheritance``), once for each ini file and config."""
        simulation_config = simulation_task.simulation_config
        simulation_project = simulation_config.simulation_project
        cache_key = (self.records_folder, simulation_config.working_directory, simulation_config.ini_file, simulation_config.config)
        with self._section_chains_lock:
            if cache_key in self._section_chains:
                return self._section_chains[cache_key]
        args = [simulation_project.get_executable(mode=simulation_task.mode), *simulation_project.get_default_args(), "-s", "-f", simulation_config.ini_file, "-c", simulation_config.config, "-q", "sectioninheritance"]
        # the query is not a test run: its profile goes nowhere
        env = {**simulation_project.get_env(mode=simulation_task.mode), "LLVM_PROFILE_FILE": os.devnull}
        result = subprocess.run(args, cwd=working_directory, env=env, capture_output=True, text=True)
        sections = read_section_chain(result.stdout) if result.returncode == 0 else None
        with self._section_chains_lock:
            self._section_chains[cache_key] = sections
        return sections

def get_test_map_simulation_runner_class(records_folder, kind):
    """
    Returns the ``simulation_runner_class`` that writes the records of the test map into
    *records_folder* for the tests of *kind* (for example ``fingerprint``). It compiles the file
    trace library into the records folder.
    """
    factory = TestMapRecorderFactory(records_folder, kind)
    return functools.partial(TestMapSimulationRunner, factory.records_folder, kind, factory.trace_library)
