
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
    def __init__(self, simulation_project, working_directory, test_file_name, mode="debug", debug=False, remove_launch=True, **kwargs):
        super().__init__(**kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.simulation_project = simulation_project
        self.working_directory = working_directory
        self.test_file_name = test_file_name
        self.mode = mode
        self.debug = debug
        self.remove_launch = remove_launch

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
        test_binary_name = re.sub(r"\.test", "", self.test_file_name)
        test_directory = os.path.join(self.working_directory, f"work/{test_binary_name}")
        has_lib = os.path.exists(os.path.join(self.working_directory, "lib"))
        os.makedirs(test_directory, exist_ok=True)
        args = ["opp_test", "gen", "-v", self.test_file_name]
        subprocess_result = run_command_with_logging(args, cwd=self.working_directory, env=self.simulation_project.get_env(), command_line_logger=_logger)
        if subprocess_result.returncode != 0:
            return self.task_result_class(self, result="ERROR", expected_result=expected_result, stderr=subprocess_result.stderr)
        library_name = self.simulation_project.dynamic_libraries[0]
        library_folder = self.simulation_project.get_library_folder_full_path()
        include_folders = [self.simulation_project.get_full_path(f) for f in self.simulation_project.include_folders]
        args = ["opp_makemake", "-f", "--deep", f"-l{library_name}{binary_suffix}", f"-L{library_folder}", *([f"-ltest{binary_suffix}", "-L../../lib"] if has_lib else []), "-P", test_directory, *[f"-I{d}" for d in include_folders], *(["-I../../lib"] if has_lib else [])]
        subprocess_result = run_command_with_logging(args, cwd=test_directory, env=self.simulation_project.get_env(), command_line_logger=_logger)
        if subprocess_result.returncode != 0:
            return self.task_result_class(self, result="ERROR", expected_result=expected_result, stderr=subprocess_result.stderr)
        args = ["make", f"MODE={self.mode}", "-j", str(multiprocessing.cpu_count())]
        subprocess_result = run_command_with_logging(args, cwd=test_directory, env=self.simulation_project.get_env(), command_line_logger=_logger)
        if subprocess_result.returncode != 0:
            return self.task_result_class(self, result="ERROR", expected_result=expected_result, stderr=subprocess_result.stderr)
        test_program = f"{test_binary_name}/{test_binary_name}{binary_suffix}"
        ned_folders = [self.simulation_project.get_full_path(f) for f in self.simulation_project.ned_folders]
        simulation_args = ["--check-signals=false", f"-l{library_name}", "-n", ":".join(ned_folders + ["."] + (["../../lib"] if has_lib else []))]
        if not self.debug:
            args = ["opp_test", "run", "-v", "-p", test_program, self.test_file_name, "-a", *simulation_args]
            subprocess_result = run_command_with_logging(args, cwd=self.working_directory, env=self.simulation_project.get_env(), command_line_logger=_logger)
            stdout = subprocess_result.stdout
        else:
            ide_opp_test = IdeOppTest(remove_launch=self.remove_launch)
            ide_opp_test.args = types.SimpleNamespace(verbose=True, workdir=os.path.join(self.working_directory, "work"), mode="run", testprogram=test_program, extraargs=" ".join(simulation_args), filenames=[test_file_name])
            ide_opp_test.saveOriginalEnv()
            ide_opp_test.parse_testfile(test_file_name)
            ide_opp_test.run_tests()
            ide_opp_test.restoreOriginalEnv()
            subprocess_result = ide_opp_test.subprocess_result
            stdout = ide_opp_test.print_stream.getvalue()
            stdout = re.sub(r'\x1b\[[0-9;]*[mGKH]', '', stdout)
        stderr = subprocess_result.stderr
        match = re.search(r"Aggregate result: (\w+)", stdout)
        if match:
            result = match.group(1)
            error_message = extract_test_error_message(stdout) if result in ("ERROR", "FAIL") else None
            return self.task_result_class(self, result=result, expected_result=expected_result, stdout=stdout, stderr=stderr, error_message=error_message)
        elif subprocess_result.returncode == signal.SIGINT.value or subprocess_result.returncode == -signal.SIGINT.value:
            return self.task_result_class(self, result="CANCEL", expected_result=expected_result, reason="Cancel by user")
        else:
            return self.task_result_class(self, result="FAIL", expected_result=expected_result, reason=f"Non-zero exit code: {subprocess_result.returncode}", stdout=stdout, stderr=stderr)

def get_opp_test_tasks(test_folder, simulation_project=None, filter=".*", full_match=False, **kwargs):
    """
    Returns multiple opp test tasks matching the provided filter criteria. The returned tasks can be run by
    calling the :py:meth:`run <opp_repl.common.task.MultipleTasks.run>` method.

    Parameters:
        kwargs (dict):
            TODO

    Returns (:py:class:`MultipleTestTasks`):
        an object that contains a list of :py:class:`OppTestTask` objects matching the provided filter criteria.
        The result can be run (and re-run) without providing additional parameters.
    """
    def create_test_task(test_file_name):
        return OppTestTask(simulation_project, os.path.dirname(test_file_name), os.path.basename(test_file_name), task_result_class=TestTaskResult, **dict(kwargs, pass_keyboard_interrupt=True))
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    # Never discover .test files under a `work/` segment: that is opp_test's
    # generated scratch (each case is extracted and compiled there, and meta
    # tests write sub-`.test` files into it). On a reused workspace those copies
    # from a prior run would otherwise be picked up as phantom tasks. No source
    # tree keeps real tests under work/, so this is a no-op on a fresh checkout.
    is_scratch = lambda f: (os.sep + "work" + os.sep) in f
    test_file_names = list(builtins.filter(lambda test_file_name: not is_scratch(test_file_name) and matches_filter(test_file_name, filter, None, full_match),
                                           glob.glob(os.path.join(simulation_project.get_full_path(test_folder), "**/*.test"), recursive=True)))
    test_tasks = list(map(create_test_task, test_file_names))
    return MultipleOppTestTasks(tasks=test_tasks, simulation_project=simulation_project, test_folder=test_folder, multiple_task_results_class=MultipleTestTaskResults, **kwargs)
get_opp_test_tasks.__signature__ = combine_signatures(get_opp_test_tasks, OppTestTask.__init__)

class MultipleOppTestTasks(MultipleSimulationTestTasks):
    def __init__(self, test_folder=None, **kwargs):
        super().__init__(**kwargs)
        self.locals = locals()
        self.locals.pop("self")
        self.kwargs = kwargs
        self.test_folder = test_folder

    def run_protected(self, **kwargs):
        # Start each suite run from a clean <test_folder>/work, replicating a fresh
        # checkout. opp_test extracts and compiles each .test case under work/, and
        # "meta" tests (e.g. INET's ConvolutionalCoder*/Ieee80211*Domain, which do
        # `%file: input.test` and run a nested sub-test) leave a nested work/<sub>/
        # directory behind. On a *reused* workspace the next run's outer simulation
        # loads NED from '.' recursively, hits that stale nested package.ned, and
        # dies with a package-mismatch error — a failure that never occurs on a
        # fresh checkout. Wiping work/ up front removes all such stale artifacts.
        work_directory = os.path.join(self.simulation_project.get_full_path(self.test_folder), "work")
        if os.path.isdir(work_directory):
            shutil.rmtree(work_directory, ignore_errors=True)
        # Build the shared opp_test support lib (<test_folder>/lib -> libtest) up front,
        # UNCONDITIONALLY — even under --no-build. --no-build only skips rebuilding the
        # simulation project; each .test case is still compiled here (see OppTestTask)
        # and links -ltest, so the lib must exist regardless of the project-build flag.
        # Idempotent: make no-ops when the lib is already up to date.
        lib_directory = os.path.join(self.simulation_project.get_full_path(self.test_folder), "lib")
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
