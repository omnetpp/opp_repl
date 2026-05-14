import logging
import os
import re
import shutil
import signal
import subprocess

from opp_repl.common.task import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

# General task base classes parameterized by their inputs/outputs. They are
# build-system agnostic and have no dependency on SimulationProject. Project-
# specific behavior (deriving these parameters from a SimulationProject or an
# OmnetppProject) lives in the build.py / build_omnetpp.py modules.

class BuildTaskResult(TaskResult):
    def __init__(self, possible_results=["DONE", "SKIP", "CANCEL", "ERROR"], possible_result_colors=[COLOR_GREEN, COLOR_CYAN, COLOR_CYAN, COLOR_RED], **kwargs):
        super().__init__(possible_results=possible_results, possible_result_colors=possible_result_colors, **kwargs)

class MultipleBuildTaskResults(MultipleTaskResults):
    def __init__(self, possible_results=["DONE", "SKIP", "CANCEL", "ERROR"], possible_result_colors=[COLOR_GREEN, COLOR_CYAN, COLOR_CYAN, COLOR_RED], **kwargs):
        super().__init__(possible_results=possible_results, possible_result_colors=possible_result_colors, **kwargs)
        if self.result == "SKIP":
            self.expected = True

class BuildTask(Task):
    def __init__(self, working_dir=None, task_result_class=BuildTaskResult, **kwargs):
        super().__init__(task_result_class=task_result_class, **kwargs)
        self.working_dir = working_dir

    def _resolve(self, file_path):
        if file_path is None:
            return None
        return file_path if os.path.isabs(file_path) else os.path.join(self.working_dir, file_path)

    def is_up_to_date(self):
        def get_mtime(p):
            full = self._resolve(p)
            return os.path.getmtime(full) if full and os.path.exists(full) else None
        input_files = self.get_input_files()
        output_files = self.get_output_files()
        input_times = list(map(get_mtime, input_files))
        output_times = list(map(get_mtime, output_files))
        result = input_times and output_times and \
                 not list(filter(lambda t: t is None, input_times)) and \
                 not list(filter(lambda t: t is None, output_times)) and \
                 max(input_times) < min(output_times)
        _logger.debug(f"  {self.name} is_up_to_date={result}: input_files={input_files}, output_files={output_files}, input_times={input_times}, output_times={output_times}")
        return result

    def run_protected(self, **kwargs):
        args = self.get_arguments()
        subprocess_result = run_command_with_logging(args, cwd=self.working_dir)
        if subprocess_result.returncode == signal.SIGINT.value or subprocess_result.returncode == -signal.SIGINT.value:
            return self.task_result_class(task=self, subprocess_result=subprocess_result, result="CANCEL", reason="Cancel by user")
        elif subprocess_result.returncode == 0:
            return self.task_result_class(task=self, subprocess_result=subprocess_result, result="DONE")
        else:
            error_message = subprocess_result.stderr.strip() if subprocess_result.stderr else None
            return self.task_result_class(task=self, subprocess_result=subprocess_result, result="ERROR", reason=f"Non-zero exit code: {subprocess_result.returncode}", error_message=error_message)

    def _ensure_output_dirs(self):
        for output_file in self.get_output_files():
            full_path = self._resolve(output_file)
            if full_path:
                directory = os.path.dirname(full_path)
                if directory and not os.path.exists(directory):
                    try:
                        os.makedirs(directory)
                    except FileExistsError:
                        pass


class CppCompileTask(BuildTask):
    """
    Compiles a single C/C++ source file to an object file. The full toolchain
    invocation is materialized from explicit parameters; no project context is
    required.
    """

    def __init__(self, working_dir=None, compiler=None, cxxflags=None, cflags=None,
                 defines=None, include_dirs=None, input_file=None, output_file=None,
                 dependency_file=None, extra_args=None, name="C++ compile task", **kwargs):
        super().__init__(working_dir=working_dir, name=name, **kwargs)
        self.compiler = compiler or ["c++"]
        self.cxxflags = cxxflags or []
        self.cflags = cflags or []
        self.defines = defines or []
        self.include_dirs = include_dirs or []
        self.input_file = input_file
        self.output_file = output_file
        self.dependency_file = dependency_file
        self.extra_args = extra_args or []

    def get_action_string(self, **kwargs):
        return "Compiling"

    def get_parameters_string(self, **kwargs):
        return self.input_file

    def get_input_files(self):
        dep = self._resolve(self.dependency_file) if self.dependency_file else None
        if dep and os.path.exists(dep):
            dependency = read_dependency_file(dep)
            target = self.output_file
            if target in dependency:
                return dependency[target]
            if dependency:
                return next(iter(dependency.values()))
        return [self.input_file]

    def get_output_files(self):
        return [self.output_file]

    def get_arguments(self):
        args = [*self.compiler, "-c",
                *self.cxxflags,
                *self.cflags,
                *self.defines,
                *[f"-I{p}" for p in self.include_dirs],
                *self.extra_args]
        if self.dependency_file:
            args += ["-MF", self.dependency_file]
        args += ["-o", self.output_file, self.input_file]
        return args

    def run_protected(self, **kwargs):
        self._ensure_output_dirs()
        return super().run_protected(**kwargs)


class LinkTask(BuildTask):
    """
    Links a library or executable from object files. Variant is selected by
    ``type``: ``"executable"``, ``"shared"`` (dynamic library), or ``"static"``.
    """

    def __init__(self, working_dir=None, linker=None, ldflags=None,
                 input_files=None, output_file=None, libraries=None,
                 library_dirs=None, rpath_dirs=None, type="shared",
                 ar=None, ranlib=None, whole_archive_on=None, whole_archive_off=None,
                 as_needed_off=None, extra_args=None, name="Link task", **kwargs):
        super().__init__(working_dir=working_dir, name=name, **kwargs)
        self.linker = linker or ["c++"]
        self.ldflags = ldflags or []
        self.input_files = input_files or []
        self.output_file = output_file
        self.libraries = libraries or []
        self.library_dirs = library_dirs or []
        self.rpath_dirs = rpath_dirs or []
        self.type = type
        self.ar = ar or ["ar", "cr"]
        self.ranlib = ranlib
        self.whole_archive_on = whole_archive_on
        self.whole_archive_off = whole_archive_off
        self.as_needed_off = as_needed_off
        self.extra_args = extra_args or []

    def get_action_string(self, **kwargs):
        return "Linking"

    def get_parameters_string(self, **kwargs):
        return os.path.basename(self.output_file) if self.output_file else ""

    def get_input_files(self):
        return list(self.input_files)

    def get_output_files(self):
        return [self.output_file]

    def get_arguments(self):
        if self.type == "static":
            args = [*self.ar, self.output_file, *self.input_files]
            return args
        args = [*self.linker,
                *self.ldflags,
                *[f"-L{p}" for p in self.library_dirs],
                "-o", self.output_file,
                *self.input_files,
                *[f"-Wl,-rpath,{p}" for p in self.rpath_dirs],
                *self.libraries,
                *self.extra_args]
        return args

    def run_protected(self, **kwargs):
        self._ensure_output_dirs()
        result = super().run_protected(**kwargs)
        if result.result == "DONE" and self.type == "static" and self.ranlib:
            ranlib_cmd = self.ranlib if isinstance(self.ranlib, list) else [self.ranlib]
            subprocess.run([*ranlib_cmd, self.output_file], cwd=self.working_dir)
        return result


class MsgCompileTask(BuildTask):
    """
    Runs ``opp_msgc`` on a ``.msg`` file to generate ``_m.cc`` and ``_m.h``.
    """

    def __init__(self, working_dir=None, msgc="opp_msgc", flags=None,
                 import_paths=None, include_paths=None, dll_symbol=None,
                 input_file=None, output_files=None, dependency_file=None,
                 name="MSG compile task", **kwargs):
        super().__init__(working_dir=working_dir, name=name, **kwargs)
        self.msgc = msgc
        self.flags = flags if flags is not None else ["--msg6", "-s", "_m.cc"]
        self.import_paths = import_paths or []
        self.include_paths = include_paths or []
        self.dll_symbol = dll_symbol
        self.input_file = input_file
        self.output_files = output_files or []
        self.dependency_file = dependency_file

    def get_action_string(self, **kwargs):
        return "Generating"

    def get_parameters_string(self, **kwargs):
        return self.output_files[0] if self.output_files else self.input_file

    def get_input_files(self):
        return [self.input_file]

    def get_output_files(self):
        return list(self.output_files)

    def get_arguments(self):
        args = [self.msgc, *self.flags]
        if self.dependency_file:
            args += ["-MD", "-MP", "-MF", self.dependency_file]
        args += [f"-I{p}" for p in self.import_paths]
        args += [f"-I{p}" for p in self.include_paths]
        if self.dll_symbol:
            args.append(f"-P{self.dll_symbol}_API")
        args.append(self.input_file)
        return args


class CopyBinaryTask(BuildTask):
    """
    Copies a single file from ``source_file`` to ``target_file``. Optionally
    runs ``postprocess_command`` (a list) on the destination afterwards.
    """

    def __init__(self, working_dir=None, source_file=None, target_file=None,
                 postprocess_command=None, name="copy task", **kwargs):
        super().__init__(working_dir=working_dir, name=name, **kwargs)
        self.source_file = source_file
        self.target_file = target_file
        self.postprocess_command = postprocess_command

    def get_action_string(self, **kwargs):
        return "Copying"

    def get_parameters_string(self, **kwargs):
        return self.target_file

    def get_input_files(self):
        return [self.source_file]

    def get_output_files(self):
        return [self.target_file]

    def run_protected(self, **kwargs):
        target_full = self._resolve(self.target_file)
        source_full = self._resolve(self.source_file)
        os.makedirs(os.path.dirname(target_full), exist_ok=True)
        if os.path.exists(target_full):
            os.remove(target_full)
        shutil.copy(source_full, target_full)
        if self.postprocess_command:
            subprocess.run([*self.postprocess_command, target_full], cwd=self.working_dir)
        return self.task_result_class(task=self, result="DONE")


class YaccTask(BuildTask):
    """Runs a yacc/bison generator: input ``.y`` -> ``.cc`` / ``.h``."""

    def __init__(self, working_dir=None, yacc="bison", flags=None,
                 input_file=None, output_files=None, name="YACC task", **kwargs):
        super().__init__(working_dir=working_dir, name=name, **kwargs)
        self.yacc = yacc
        self.flags = flags or []
        self.input_file = input_file
        self.output_files = output_files or []

    def get_action_string(self, **kwargs):
        return "Generating"

    def get_parameters_string(self, **kwargs):
        return self.output_files[0] if self.output_files else self.input_file

    def get_input_files(self):
        return [self.input_file]

    def get_output_files(self):
        return list(self.output_files)

    def get_arguments(self):
        return [self.yacc, *self.flags, self.input_file]

    def run_protected(self, **kwargs):
        self._ensure_output_dirs()
        return super().run_protected(**kwargs)


class LexTask(BuildTask):
    """Runs a lex/flex generator: input ``.lex`` -> ``.cc`` / ``.h``."""

    def __init__(self, working_dir=None, lex="flex", flags=None,
                 input_file=None, output_files=None, name="LEX task", **kwargs):
        super().__init__(working_dir=working_dir, name=name, **kwargs)
        self.lex = lex
        self.flags = flags or []
        self.input_file = input_file
        self.output_files = output_files or []

    def get_action_string(self, **kwargs):
        return "Generating"

    def get_parameters_string(self, **kwargs):
        return self.output_files[0] if self.output_files else self.input_file

    def get_input_files(self):
        return [self.input_file]

    def get_output_files(self):
        return list(self.output_files)

    def get_arguments(self):
        return [self.lex, *self.flags, self.input_file]

    def run_protected(self, **kwargs):
        self._ensure_output_dirs()
        return super().run_protected(**kwargs)


class PerlGenerateTask(BuildTask):
    """Runs a Perl generator script that produces one or more files."""

    def __init__(self, working_dir=None, perl="perl", script=None, script_args=None,
                 input_files=None, output_files=None, name="Perl generate task", **kwargs):
        super().__init__(working_dir=working_dir, name=name, **kwargs)
        self.perl = perl
        self.script = script
        self.script_args = script_args or []
        self.declared_input_files = input_files or ([script] if script else [])
        self.output_files = output_files or []

    def get_action_string(self, **kwargs):
        return "Generating"

    def get_parameters_string(self, **kwargs):
        return self.output_files[0] if self.output_files else (self.script or "")

    def get_input_files(self):
        return list(self.declared_input_files)

    def get_output_files(self):
        return list(self.output_files)

    def get_arguments(self):
        return [self.perl, self.script, *self.script_args]

    def run_protected(self, **kwargs):
        self._ensure_output_dirs()
        return super().run_protected(**kwargs)


class MocTask(BuildTask):
    """Runs Qt ``moc`` on a header: input ``.h`` -> ``moc_*.cpp`` (or as configured)."""

    def __init__(self, working_dir=None, moc="moc", defines=None, flags=None,
                 input_file=None, output_file=None, name="MOC task", **kwargs):
        super().__init__(working_dir=working_dir, name=name, **kwargs)
        self.moc = moc
        self.defines = defines or []
        self.flags = flags or []
        self.input_file = input_file
        self.output_file = output_file

    def get_action_string(self, **kwargs):
        return "MOC"

    def get_parameters_string(self, **kwargs):
        return self.output_file

    def get_input_files(self):
        return [self.input_file]

    def get_output_files(self):
        return [self.output_file]

    def get_arguments(self):
        return [self.moc, *self.defines, *self.flags, "-o", self.output_file, self.input_file]

    def run_protected(self, **kwargs):
        self._ensure_output_dirs()
        return super().run_protected(**kwargs)


class UicTask(BuildTask):
    """Runs Qt ``uic`` on a ``.ui`` file to generate a header."""

    def __init__(self, working_dir=None, uic="uic", flags=None,
                 input_file=None, output_file=None, name="UIC task", **kwargs):
        super().__init__(working_dir=working_dir, name=name, **kwargs)
        self.uic = uic
        self.flags = flags or []
        self.input_file = input_file
        self.output_file = output_file

    def get_action_string(self, **kwargs):
        return "UIC"

    def get_parameters_string(self, **kwargs):
        return self.output_file

    def get_input_files(self):
        return [self.input_file]

    def get_output_files(self):
        return [self.output_file]

    def get_arguments(self):
        return [self.uic, *self.flags, "-o", self.output_file, self.input_file]

    def run_protected(self, **kwargs):
        self._ensure_output_dirs()
        return super().run_protected(**kwargs)


class RccTask(BuildTask):
    """Runs Qt ``rcc`` on a ``.qrc`` file to generate a C++ source."""

    def __init__(self, working_dir=None, rcc="rcc", flags=None,
                 input_file=None, output_file=None, name="RCC task", **kwargs):
        super().__init__(working_dir=working_dir, name=name, **kwargs)
        self.rcc = rcc
        self.flags = flags or []
        self.input_file = input_file
        self.output_file = output_file

    def get_action_string(self, **kwargs):
        return "RCC"

    def get_parameters_string(self, **kwargs):
        return self.output_file

    def get_input_files(self):
        return [self.input_file]

    def get_output_files(self):
        return [self.output_file]

    def get_arguments(self):
        return [self.rcc, *self.flags, "-o", self.output_file, self.input_file]

    def run_protected(self, **kwargs):
        self._ensure_output_dirs()
        return super().run_protected(**kwargs)
