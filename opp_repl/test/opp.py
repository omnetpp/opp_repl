
"""
This module provides functionality for running multiple tests using the :command:`opp_test` command.

The main function is :py:func:`run_opp_tests`. It allows running multiple tests matching the provided
filter criteria.
"""

import builtins
import glob
import importlib.util
import io
import logging
import os
import shutil
import signal
import subprocess
import types

from opp_repl.simulation.project import *
from opp_repl.test.task import *
from opp_repl.test.simulation import *

_logger = logging.getLogger(__name__)

if importlib.util.find_spec("omnetpp") and importlib.util.find_spec("omnetpp.test"):
    from omnetpp.test import *

    class IdeOppTest(OppTest):
        def __init__(self, remove_launch=True, **kwargs):
            super().__init__(**kwargs)
            self.print_stream = io.StringIO()
            self.remove_launch = remove_launch

        def lprint(self, level, *args, **kwargs):
            if level <= self.args.verbose:
                print(*args, **kwargs, file=self.print_stream)

        def exec_program(self, cmd, wdir, outfile, errfile):
            args = list(filter(None, cmd.split(' ')))
            program = os.path.join(wdir, args[0])
            name = os.path.basename(program)
            args = args[1:]
            self.subprocess_result = debug_program(name, program, args, wdir, remove_launch=self.remove_launch)
            self.lprint(1, self.subprocess_result.stdout)
            with open(os.path.join(wdir, outfile), "w") as f:
                f.write(self.subprocess_result.stdout)
            with open(os.path.join(wdir, errfile), "w") as f:
                f.write(self.subprocess_result.stderr)
            return self.subprocess_result.returncode

def extract_test_error_message(stdout):
    # opp_test prints one line per failed test in the form "*** <testname>: ERROR (<reason>)"
    # (see omnetpp/test.py testerror/testfailed). The reason is on stdout, not stderr, so extract
    # it here; otherwise the task result would report "<No error message>". Strip any ANSI color
    # codes first (the debug/IdeOppTest path may embed them before this point).
    text = re.sub(r"\x1b\[[0-9;]*[mGKH]", "", stdout)
    messages = re.findall(r"^\*\*\* [^\n]*?: (?:ERROR|FAIL) \((.*)\)[ \t]*$", text, re.MULTILINE)
    return "\n".join(messages) if messages else None

class OppTestTask(TestTask):
    def __init__(self, simulation_project, working_directory, test_file_name, mode="debug", debug=False, remove_launch=True, lib_directory=None, lib_name="test", **kwargs):
        super().__init__(**kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.simulation_project = simulation_project
        # the folder the test is generated and run from; test_file_name is relative to it and
        # may name a subfolder (a test of a suite folder, see get_opp_test_tasks)
        self.working_directory = working_directory
        self.test_file_name = test_file_name
        self.mode = mode
        self.debug = debug
        self.remove_launch = remove_launch
        # the support library the test links, <working_directory>/lib unless the project names
        # another one (INET's protocol tests share tests/protocol/lib, libprotocoltest)
        self.lib_directory = lib_directory or os.path.join(working_directory, "lib")
        self.lib_name = lib_name

    def has_testprog(self):
        """A test that names its own program with ``%testprog`` never runs the test binary."""
        if not hasattr(self, "_has_testprog"):
            with open(os.path.join(self.working_directory, self.test_file_name), encoding="utf-8", errors="replace") as f:
                self._has_testprog = re.search(r"^%testprog:", f.read(), re.MULTILINE) is not None
        return self._has_testprog

    def get_work_directory(self):
        """The folder opp_test extracts the test into, relative to the working directory: work/ of
        the working directory, because the ini files of a test may reach shared files by paths
        relative to it (INET's wifi tests include ../../ini/_b.ini). A %testprog test builds
        nothing and has no such paths, so it runs in work/ beside its .test file, and two of them
        with one file name in different subfolders do not share a folder."""
        return os.path.join(os.path.dirname(self.test_file_name), "work") if self.has_testprog() else "work"

    def get_parameters_string(self, **kwargs):
        return self.test_file_name

    def get_expected_result(self):
        """The declared expected result of this test, read from a
        ``%# expected-result: <PASS|FAIL|ERROR>`` comment line in the .test file.

        opp_test itself ignores ``%#`` comment lines (omnetpp/test.py), so this is a
        metadata annotation for the wrapper only -- the honest analogue of opp_repl's
        commented-out ``#expected-result = "..."`` INI key. Defaults to ``PASS``."""
        if not hasattr(self, "_expected_result"):
            self._expected_result = "PASS"
            test_file_path = os.path.join(self.working_directory, self.test_file_name)
            try:
                with open(test_file_path) as f:
                    for line in f:
                        m = re.match(r"^%#\s*expected-result\s*:\s*(\w+)\s*$", line)
                        if m:
                            value = m.group(1).upper()
                            if value not in ("PASS", "FAIL", "ERROR"):
                                raise ValueError(f"invalid '%# expected-result: {m.group(1)}' in "
                                                 f"{self.test_file_name} (allowed: PASS, FAIL, ERROR)")
                            self._expected_result = value
                            break
            except (IOError, OSError):
                pass
        return self._expected_result

    def run_protected(self, **kwargs):
        binary_suffix = "_dbg" if self.mode == "debug" else ""
        expected_result = self.get_expected_result()
        test_file_name = os.path.join(self.working_directory, self.test_file_name)
        test_binary_name = os.path.basename(re.sub(r"\.test$", "", self.test_file_name))
        work_directory = self.get_work_directory()
        test_directory = os.path.join(self.working_directory, work_directory, test_binary_name)
        has_lib = os.path.exists(self.lib_directory)
        lib_relative_path = os.path.relpath(self.lib_directory, test_directory)
        os.makedirs(test_directory, exist_ok=True)
        args = ["opp_test", "gen", "-v", "-w", work_directory, self.test_file_name]
        subprocess_result = run_command_with_logging(args, cwd=self.working_directory, env=self.simulation_project.get_env(), command_line_logger=_logger)
        if subprocess_result.returncode != 0:
            return self.task_result_class(self, result="ERROR", expected_result=expected_result, stderr=subprocess_result.stderr)
        library_name = self.simulation_project.dynamic_libraries[0]
        library_folder = self.simulation_project.get_library_folder_full_path()
        include_folders = [self.simulation_project.get_full_path(f) for f in self.simulation_project.include_folders]
        # a header of the working directory or beside the .test file, such as INET's
        # tests/protocol/wifi/WifiTestSupport.h and tests/protocol/tcp/rfc/TcpMutations.h
        include_folders += [self.working_directory, os.path.dirname(test_file_name)]
        # building a binary for a %testprog test costs a makefile and a link per test for nothing
        if not self.has_testprog():
            args = ["opp_makemake", "-f", "--deep", f"-l{library_name}{binary_suffix}", f"-L{library_folder}", *([f"-l{self.lib_name}{binary_suffix}", f"-L{lib_relative_path}"] if has_lib else []), "-P", test_directory, *[f"-I{d}" for d in include_folders], *([f"-I{lib_relative_path}"] if has_lib else [])]
            subprocess_result = run_command_with_logging(args, cwd=test_directory, env=self.simulation_project.get_env(), command_line_logger=_logger)
            if subprocess_result.returncode != 0:
                return self.task_result_class(self, result="ERROR", expected_result=expected_result, stderr=subprocess_result.stderr)
            args = ["make", f"MODE={self.mode}", "-j", str(multiprocessing.cpu_count())]
            subprocess_result = run_command_with_logging(args, cwd=test_directory, env=self.simulation_project.get_env(), command_line_logger=_logger)
            if subprocess_result.returncode != 0:
                return self.task_result_class(self, result="ERROR", expected_result=expected_result, stderr=subprocess_result.stderr)
        test_program = f"{test_binary_name}/{test_binary_name}{binary_suffix}"
        ned_folders = [self.simulation_project.get_full_path(f) for f in self.simulation_project.ned_folders]
        # the NED files of the working directory's ned folder, such as tests/protocol/wifi/ned
        ned_directory = os.path.join(self.working_directory, "ned")
        ned_folders += ["."] + ([lib_relative_path] if has_lib else []) + ([os.path.relpath(ned_directory, test_directory)] if os.path.isdir(ned_directory) else [])
        simulation_args = ["--check-signals=false", f"-l{library_name}", "-n", ":".join(ned_folders)]
        if not self.debug:
            args = ["opp_test", "run", "-v", "-w", work_directory, "-p", test_program, self.test_file_name, "-a", *simulation_args]
            subprocess_result = run_command_with_logging(args, cwd=self.working_directory, env=self.simulation_project.get_env(), command_line_logger=_logger)
            stdout = subprocess_result.stdout
        else:
            ide_opp_test = IdeOppTest(remove_launch=self.remove_launch)
            ide_opp_test.args = types.SimpleNamespace(verbose=True, workdir=os.path.join(self.working_directory, work_directory), mode="run", testprogram=test_program, extraargs=" ".join(simulation_args), filenames=[test_file_name])
            ide_opp_test.saveOriginalEnv()
            ide_opp_test.parse_testfile(test_file_name)
            ide_opp_test.run_tests()
            ide_opp_test.restoreOriginalEnv()
            subprocess_result = ide_opp_test.subprocess_result
            stdout = ide_opp_test.print_stream.getvalue()
            stdout = re.sub(r'\x1b\[[0-9;]*[mGKH]', '', stdout)
        stderr = subprocess_result.stderr
        # opp_test counts a test whose program prints "#SKIPPED" as skipped, and still prints
        # "Aggregate result: PASS" for a run in which nothing failed; a skip must not read as a pass
        skipped = re.search(r"^\*\*\* \S+: SKIPPED \((.*)\)\s*$", stdout, re.MULTILINE)
        if skipped:
            return self.task_result_class(self, result="SKIP", expected_result="SKIP", reason=skipped.group(1), stdout=stdout, stderr=stderr)
        match = re.search(r"Aggregate result: (\w+)", stdout)
        if match:
            result = match.group(1)
            error_message = extract_test_error_message(stdout) if result in ("ERROR", "FAIL") else None
            return self.task_result_class(self, result=result, expected_result=expected_result, stdout=stdout, stderr=stderr, error_message=error_message)
        elif subprocess_result.returncode == signal.SIGINT.value or subprocess_result.returncode == -signal.SIGINT.value:
            return self.task_result_class(self, result="CANCEL", expected_result=expected_result, reason="Cancel by user")
        else:
            return self.task_result_class(self, result="FAIL", expected_result=expected_result, reason=f"Non-zero exit code: {subprocess_result.returncode}", stdout=stdout, stderr=stderr)

def get_opp_test_tasks(test_folder, simulation_project=None, filter=".*", full_match=False, suite_folders=False, lib_folder=None, lib_name="test", **kwargs):
    """
    Returns multiple opp test tasks matching the provided filter criteria. The returned tasks can be run by
    calling the :py:meth:`run <opp_repl.common.task.MultipleTasks.run>` method.

    Parameters:
        suite_folders (bool):
            False: a test runs from the folder of its .test file. True: every direct subfolder of
            the test folder is a suite, and a test runs from its suite folder, at any depth below
            it, so that it reaches the files the whole suite shares (INET's tests/protocol).

        lib_folder (string or None):
            The support library that the tests link, relative to the project root. None: the lib
            folder of a test's working directory, if it exists.

        lib_name (string):
            The name of the support library, "test" unless the project names another one.

        kwargs (dict):
            ``working_directory_filter`` and ``exclude_working_directory_filter`` select a test by
            the test folder, its working directory or the folder of its .test file, each relative
            to the project root; a whole suite or one subfolder of it can be selected.

    Returns (:py:class:`MultipleTestTasks`):
        an object that contains a list of :py:class:`OppTestTask` objects matching the provided filter criteria.
        The result can be run (and re-run) without providing additional parameters.
    """
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    test_folder_path = simulation_project.get_full_path(test_folder)
    project_folder = simulation_project.get_full_path(".")
    def get_working_directory(test_file_name):
        if suite_folders:
            return os.path.join(test_folder_path, os.path.relpath(test_file_name, test_folder_path).split(os.sep)[0])
        return os.path.dirname(test_file_name)
    def create_test_task(test_file_name):
        working_directory = get_working_directory(test_file_name)
        return OppTestTask(simulation_project, working_directory, os.path.relpath(test_file_name, working_directory),
                           lib_directory=simulation_project.get_full_path(lib_folder) if lib_folder else None, lib_name=lib_name,
                           task_result_class=TestTaskResult, **dict(kwargs, pass_keyboard_interrupt=True))
    working_directory_filter = kwargs.get("working_directory_filter", None)
    exclude_working_directory_filter = kwargs.get("exclude_working_directory_filter", None)
    def matches_working_directory(test_file_name):
        folders = [os.path.relpath(folder, project_folder) for folder in (test_folder_path, get_working_directory(test_file_name), os.path.dirname(test_file_name))]
        return (working_directory_filter is None or any(matches_filter(folder, working_directory_filter, None, full_match) for folder in folders)) and \
               (exclude_working_directory_filter is None or not any(matches_filter(folder, exclude_working_directory_filter, None, full_match) for folder in folders))
    # Never discover .test files under a `work/` segment: that is opp_test's
    # generated scratch (each case is extracted and compiled there, and meta
    # tests write sub-`.test` files into it). On a reused workspace those copies
    # from a prior run would otherwise be picked up as phantom tasks. No source
    # tree keeps real tests under work/, so this is a no-op on a fresh checkout.
    is_scratch = lambda f: (os.sep + "work" + os.sep) in f
    test_file_names = list(builtins.filter(lambda test_file_name: not is_scratch(test_file_name) and matches_filter(test_file_name, filter, None, full_match) and matches_working_directory(test_file_name),
                                           glob.glob(os.path.join(test_folder_path, "**/*.test"), recursive=True)))
    test_tasks = list(map(create_test_task, test_file_names))
    return MultipleOppTestTasks(tasks=test_tasks, simulation_project=simulation_project, test_folder=test_folder, lib_folder=lib_folder, multiple_task_results_class=MultipleTestTaskResults, **kwargs)
get_opp_test_tasks.__signature__ = combine_signatures(get_opp_test_tasks, OppTestTask.__init__)

class MultipleOppTestTasks(MultipleSimulationTestTasks):
    def __init__(self, test_folder=None, lib_folder=None, **kwargs):
        super().__init__(**kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.test_folder = test_folder
        self.lib_folder = lib_folder

    def run_protected(self, **kwargs):
        # Start each suite run from a clean <test_folder>/work, replicating a fresh
        # checkout. opp_test extracts and compiles each .test case under work/, and
        # "meta" tests (e.g. INET's ConvolutionalCoder*/Ieee80211*Domain, which do
        # `%file: input.test` and run a nested sub-test) leave a nested work/<sub>/
        # directory behind. On a *reused* workspace the next run's outer simulation
        # loads NED from '.' recursively, hits that stale nested package.ned, and
        # dies with a package-mismatch error — a failure that never occurs on a
        # fresh checkout. Wiping work/ up front removes all such stale artifacts: the work
        # folder of every test's working directory, and the one beside a %testprog test.
        work_directories = {os.path.join(self.simulation_project.get_full_path(self.test_folder), "work")}
        work_directories |= {os.path.join(task.working_directory, task.get_work_directory()) for task in self.tasks if isinstance(task, OppTestTask)}
        for work_directory in sorted(work_directories):
            if os.path.isdir(work_directory):
                shutil.rmtree(work_directory, ignore_errors=True)
        # Build the shared opp_test support lib (<test_folder>/lib -> libtest) up front,
        # UNCONDITIONALLY — even under --no-build. --no-build only skips rebuilding the
        # simulation project; each .test case is still compiled here (see OppTestTask)
        # and links -ltest, so the lib must exist regardless of the project-build flag.
        # Idempotent: make no-ops when the lib is already up to date.
        lib_directory = self.simulation_project.get_full_path(self.lib_folder or os.path.join(self.test_folder, "lib"))
        if os.path.isfile(os.path.join(lib_directory, "Makefile")):
            args = ["make", f"MODE={self.mode}", "-j", str(multiprocessing.cpu_count())]
            subprocess_result = run_command_with_logging(args, cwd=lib_directory, env=self.simulation_project.get_env(), command_line_logger=_logger)
            if subprocess_result.returncode != 0:
                raise Exception(f"Cannot build opp_test support lib in {lib_directory}")
        return super().run_protected(**kwargs)

class BinaryTestTask(TestTask):
    """Run a self-contained test folder that builds its own executable (via its
    own Makefile) and self-checks by returning a non-zero exit code on failure.

    INET's ``tests/packet`` is the canonical case: ``UnitTest.cc`` compiles to a
    standalone ``packet_test`` program that asserts internally and exits
    non-zero if any assertion fails — it is *not* an ``opp_test`` ``.test``
    suite (the folder contains no ``.test`` files). The task builds the folder,
    runs ``./<executable>[_dbg] -s -u Cmdenv -c <config>``, and maps exit code 0
    → PASS. Everything project-specific (``test_folder``/``executable``/
    ``config``) comes from the project's ``.opp`` ``test_parameters`` defaults,
    so opp_repl stays generic and the project carries no runner code."""
    def __init__(self, simulation_project, test_folder, executable, config="UnitTest", ini_file=None, mode="debug", task_result_class=TestTaskResult, **kwargs):
        super().__init__(task_result_class=task_result_class, **kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.simulation_project = simulation_project
        self.test_folder = test_folder
        self.executable = executable
        self.config = config
        self.ini_file = ini_file
        self.mode = mode

    def get_parameters_string(self, **kwargs):
        return f"{self.test_folder} -c {self.config}"

    def run_protected(self, **kwargs):
        binary_suffix = "_dbg" if self.mode == "debug" else ""
        working_directory = self.simulation_project.get_full_path(self.test_folder)
        env = self.simulation_project.get_env()
        # Build the folder's own executable (links the already-built project lib).
        build_args = ["make", "-s", f"MODE={self.mode}", "-j", str(multiprocessing.cpu_count())]
        subprocess_result = run_command_with_logging(build_args, cwd=working_directory, env=env, command_line_logger=_logger)
        if subprocess_result.returncode != 0:
            return self.task_result_class(self, result="ERROR", stderr=subprocess_result.stderr)
        run_args = [f"./{self.executable}{binary_suffix}", "-s", "-u", "Cmdenv", "-c", self.config]
        if self.ini_file:
            run_args += ["-f", self.ini_file]
        subprocess_result = run_command_with_logging(run_args, cwd=working_directory, env=env, command_line_logger=_logger)
        if subprocess_result.returncode == 0:
            return self.task_result_class(self, result="PASS", stdout=subprocess_result.stdout, stderr=subprocess_result.stderr)
        elif subprocess_result.returncode in (signal.SIGINT.value, -signal.SIGINT.value):
            return self.task_result_class(self, result="CANCEL", reason="Cancel by user")
        else:
            return self.task_result_class(self, result="FAIL", reason=f"Non-zero exit code: {subprocess_result.returncode}", stdout=subprocess_result.stdout, stderr=subprocess_result.stderr)

def get_binary_test_tasks(test_folder, executable, simulation_project=None, config="UnitTest", ini_file=None, filter=".*", full_match=False, **kwargs):
    """Return the single :py:class:`BinaryTestTask` for *test_folder* wrapped in a
    ``MultipleTestTasks`` so it runs and reports like every other test kind."""
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    task = BinaryTestTask(simulation_project, test_folder, executable, config=config, ini_file=ini_file, task_result_class=TestTaskResult, **dict(kwargs, pass_keyboard_interrupt=True))
    # dict(kwargs, ...) overrides rather than duplicates keys the caller may also
    # pass in kwargs (e.g. a default `concurrent`), which would otherwise raise
    # "got multiple values for keyword argument".
    return MultipleTestTasks(tasks=[task], **dict(kwargs, concurrent=False, multiple_task_results_class=MultipleTestTaskResults))

def run_opp_tests(test_folder, **kwargs):
    """
    Runs one or more tests using the :command:`opp_test` command that match the provided filter criteria.

    Parameters:
        kwargs (dict):
            The filter criteria parameters are inherited from the :py:func:`get_opp_test_tasks` function.

    Returns (:py:class:`MultipleTestTaskResults`):
        an object that contains a list of :py:class:`TestTaskResult` objects. Each object describes the result of running one test task.
    """
    kwargs = apply_project_test_defaults("opp", kwargs)
    multiple_test_tasks = get_opp_test_tasks(test_folder, **kwargs)
    return multiple_test_tasks.run(**kwargs)

def _run_folder_opp_tests(kind, **kwargs):
    """Run the opp ``.test`` suites for a folder-scoped kind (unit/module/queueing/…).

    These kinds are the generic ``opp`` runner scoped to a project-specific test
    folder (INET splits its opp_test suites into tests/unit, tests/module, …). The
    folder comes from ``test_parameters[kind]["defaults"]["test_folder"]`` in the
    project's ``.opp``, so opp_ci stays generic and the mapping lives with the
    project. Falls back to the cwd if the project declares no folder."""
    kwargs = apply_project_test_defaults(kind, kwargs)
    test_folder = kwargs.pop("test_folder", os.getcwd())
    multiple_test_tasks = get_opp_test_tasks(test_folder, **kwargs)
    return multiple_test_tasks.run(**kwargs)

def run_binary_tests(kind, **kwargs):
    """Run a project's self-checking binary test folder for *kind* (see
    :py:class:`BinaryTestTask`). The ``test_folder``/``executable``/``config``
    come from the project's ``.opp`` ``test_parameters[kind]["defaults"]``."""
    kwargs = apply_project_test_defaults(kind, kwargs)
    test_folder = kwargs.pop("test_folder")
    executable = kwargs.pop("executable")
    config = kwargs.pop("config", "UnitTest")
    ini_file = kwargs.pop("ini_file", None)
    multiple_test_tasks = get_binary_test_tasks(test_folder, executable, config=config, ini_file=ini_file, **kwargs)
    return multiple_test_tasks.run(**kwargs)

def run_unit_tests(**kwargs):
    return _run_folder_opp_tests("unit", **kwargs)

def run_module_tests(**kwargs):
    return _run_folder_opp_tests("module", **kwargs)

def run_packet_tests(**kwargs):
    # INET's tests/packet is a single self-checking binary, not a .test suite.
    return run_binary_tests("packet", **kwargs)

def run_queueing_tests(**kwargs):
    return _run_folder_opp_tests("queueing", **kwargs)

def run_protocol_tests(**kwargs):
    return _run_folder_opp_tests("protocol", **kwargs)
run_opp_tests.__signature__ = combine_signatures(run_opp_tests, get_opp_test_tasks)
