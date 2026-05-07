import logging
import signal
import subprocess

from opp_repl.common.task import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

# TODO: experimental native Python build tool

class BuildTaskResult(TaskResult):
    def __init__(self, possible_results=["DONE", "SKIP", "CANCEL", "ERROR"], possible_result_colors=[COLOR_GREEN, COLOR_CYAN, COLOR_CYAN, COLOR_RED], **kwargs):
        super().__init__(possible_results=possible_results, possible_result_colors=possible_result_colors, **kwargs)

class MultipleBuildTaskResults(MultipleTaskResults):
    def __init__(self, possible_results=["DONE", "SKIP", "CANCEL", "ERROR"], possible_result_colors=[COLOR_GREEN, COLOR_CYAN, COLOR_CYAN, COLOR_RED], **kwargs):
        super().__init__(possible_results=possible_results, possible_result_colors=possible_result_colors, **kwargs)
        if self.result == "SKIP":
            self.expected = True

class BuildTask(Task):
    def __init__(self, simulation_project=None, task_result_class=BuildTaskResult, **kwargs):
        super().__init__(task_result_class=task_result_class, **kwargs)
        self.simulation_project = simulation_project

    def is_up_to_date(self):
        def get_file_modification_time(file_path):
            full_file_path = self.simulation_project.get_full_path(file_path)
            return os.path.getmtime(full_file_path) if os.path.exists(full_file_path) else None
        def get_file_modification_times(file_paths):
            return list(map(get_file_modification_time, file_paths))
        input_file_modification_times = get_file_modification_times(self.get_input_files())
        output_file_modification_times = get_file_modification_times(self.get_output_files())
        return input_file_modification_times and output_file_modification_times and \
               not list(filter(lambda timestamp: timestamp is None, output_file_modification_times)) and \
               max(input_file_modification_times) < min(output_file_modification_times)

    def run(self, **kwargs):
        if self.is_up_to_date():
            return self.task_result_class(task=self, result="SKIP", expected_result="SKIP", reason="Up-to-date")
        else:
            return super().run(**kwargs)

    def run_protected(self, **kwargs):
        args = self.get_arguments()
        subprocess_result = run_command_with_logging(args, cwd=self.simulation_project.get_full_path("."))
        if subprocess_result.returncode == signal.SIGINT.value or subprocess_result.returncode == -signal.SIGINT.value:
            return self.task_result_class(task=self, subprocess_result=subprocess_result, result="CANCEL", reason="Cancel by user")
        elif subprocess_result.returncode == 0:
            return self.task_result_class(task=self, subprocess_result=subprocess_result, result="DONE")
        else:
            error_message = subprocess_result.stderr.strip() if subprocess_result.stderr else None
            return self.task_result_class(task=self, subprocess_result=subprocess_result, result="ERROR", reason=f"Non-zero exit code: {subprocess_result.returncode}", error_message=error_message)

class MsgCompileTask(BuildTask):
    def __init__(self, simulation_project=None, file_path=None, name="MSG compile task", mode="release", makefile_inc_config=None, **kwargs):
        super().__init__(simulation_project=simulation_project, name=name, **kwargs)
        self.file_path = file_path
        self.mode = mode
        self.makefile_inc_config = makefile_inc_config

    def get_action_string(self, **kwargs):
        return "Generating"

    def get_parameters_string(self, **kwargs):
        return self.file_path

    def get_output_folder(self):
        if self.makefile_inc_config:
            return f"out/{self.makefile_inc_config.configname}"
        return f"out/clang-{self.mode}"

    def get_input_files(self):
        output_folder = self.get_output_folder()
        object_path = re.sub(r"\.msg", "_m.cc", self.file_path)
        dependency_file_path = re.sub(r"\.msg", "_m.h.d", self.file_path)
        full_file_path = self.simulation_project.get_full_path(os.path.join(output_folder, dependency_file_path))
        if os.path.exists(full_file_path):
            dependency = read_dependency_file(full_file_path)
            # KLUDGE: src folder hacked in and out
            file_paths = dependency[re.sub(r"src/", "", object_path)]
            return list(map(lambda file_path: self.simulation_project.get_full_path(os.path.join("src", file_path)), file_paths))
        else:
            return [self.file_path]

    def get_output_files(self):
        cpp_file_path = re.sub(r"\.msg", "_m.cc", self.file_path)
        header_file_path = re.sub(r"\.msg", "_m.h", self.file_path)
        return [f"{cpp_file_path}", f"{header_file_path}"]

    def get_arguments(self):
        cfg = self.makefile_inc_config
        executable = cfg.msgc if cfg else "opp_msgc"
        output_folder = self.get_output_folder()
        header_file_path = re.sub(r"\.msg", "_m.h", self.file_path)
        import_paths = list(map(lambda msg_folder: self.simulation_project.get_full_path(msg_folder), self.simulation_project.msg_folders))
        include_paths = list(map(lambda include_folder: self.simulation_project.get_full_path(include_folder), self.simulation_project.include_folders))
        dll_symbol = self.simulation_project.dll_symbol
        args = [executable,
                "--msg6",
                "-s",
                "_m.cc",
                "-MD",
                "-MP",
                "-MF",
                f"../{output_folder}/{header_file_path}.d",
                *[f"-I{p}" for p in import_paths],
                *[f"-I{p}" for p in include_paths]]
        if dll_symbol:
            args.append(f"-P{dll_symbol}_API")
        args.append(self.file_path)
        return args

class CppCompileTask(BuildTask):
    def __init__(self, simulation_project=None, file_path=None, name="C++ compile task", mode="release", makefile_inc_config=None, feature_cflags=None, **kwargs):
        super().__init__(simulation_project=simulation_project, name=name, **kwargs)
        self.file_path = file_path
        self.mode = mode
        self.makefile_inc_config = makefile_inc_config
        self.feature_cflags = feature_cflags or []

    def get_action_string(self, **kwargs):
        return "Compiling"

    def get_parameters_string(self, **kwargs):
        return self.file_path

    def get_output_folder(self):
        if self.makefile_inc_config:
            return f"out/{self.makefile_inc_config.configname}"
        return f"out/clang-{self.mode}"

    def get_input_files(self):
        output_folder = self.get_output_folder()
        object_path = re.sub(r"\.cc", ".o", self.file_path)
        dependency_file_path = re.sub(r"\.cc", ".o.d", self.file_path)
        full_file_path = self.simulation_project.get_full_path(os.path.join(output_folder, dependency_file_path))
        if os.path.exists(full_file_path):
            dependency = read_dependency_file(full_file_path)
            file_paths = dependency[os.path.join(output_folder, object_path)]
            return list(map(lambda file_path: self.simulation_project.get_full_path(file_path), file_paths))
        else:
            return [self.file_path]

    def get_output_files(self):
        output_folder = self.get_output_folder()
        object_path = re.sub(r"\.cc", ".o", self.file_path)
        return [f"{output_folder}/{object_path}"]

    def get_arguments(self):
        cfg = self.makefile_inc_config
        output_file = self.get_output_files()[0]
        sp = self.simulation_project

        if cfg:
            import shlex
            # Compiler from Makefile.inc (strip ccache prefix for direct invocation)
            cxx = cfg.cxx.split()[-1] if "ccache" in cfg.cxx else cfg.cxx
            # Base flags from Makefile.inc
            cflags = shlex.split(cfg.cflags)
            cxxflags = shlex.split(cfg.cxxflags)
            import_defines = shlex.split(cfg.import_defines) if cfg.import_defines else []
            incl_dir = cfg.omnetpp_incl_dir
        else:
            cxx = "clang++"
            cflags = ["-O3", "-DNDEBUG=1", "-MMD", "-MP", "-fPIC",
                      "-Wno-deprecated-register", "-Wno-unused-function", "-fno-omit-frame-pointer"]
            cxxflags = ["-std=c++20"]
            import_defines = ["-DOMNETPPLIBS_IMPORT"]
            incl_dir = "/usr/include"  # fallback

        # Remove -MF and its argument (the .d target from Makefile.inc evaluation)
        filtered_cflags = []
        skip_next = False
        for f in cflags:
            if skip_next:
                skip_next = False
                continue
            if f == "-MF":
                skip_next = True
                continue
            if f.startswith("-MF"):
                continue
            filtered_cflags.append(f)
        cflags = filtered_cflags

        # DLL export define
        dll_defines = []
        if sp.dll_symbol:
            dll_defines.append(f"-D{sp.dll_symbol}_EXPORT")

        # Include paths
        include_flags = [f"-I{incl_dir}"]
        include_flags += [f"-I{p}" for p in sp.get_effective_include_folders()]
        include_flags += [f"-I{p}" for p in sp.external_include_folders]

        # Project defines
        define_flags = [f"-D{d}" for d in sp.cpp_defines]

        # Extra cflags from project
        extra = sp.extra_cflags if hasattr(sp, 'extra_cflags') else []

        args = [cxx, "-c",
                *cxxflags,
                *cflags,
                *import_defines,
                *dll_defines,
                *self.feature_cflags,
                *include_flags,
                *define_flags,
                *extra,
                "-MF", f"{output_file}.d",
                "-o", output_file,
                self.file_path]
        return args

    def run_protected(self, **kwargs):
        output_file = self.get_output_files()[0]
        directory = os.path.dirname(self.simulation_project.get_full_path(output_file))
        if not os.path.exists(directory):
            try:
                os.makedirs(directory)
            except:
                pass
        return super().run_protected(**kwargs)

class LinkTask(BuildTask):
    def __init__(self, simulation_project=None, name="Link task", type="dynamic library", mode="release", compile_tasks=[], makefile_inc_config=None, feature_ldflags=None, **kwargs):
        super().__init__(simulation_project=simulation_project, name=name, **kwargs)
        self.type = type
        self.mode = mode
        self.compile_tasks = compile_tasks
        self.makefile_inc_config = makefile_inc_config
        self.feature_ldflags = feature_ldflags or []

    def get_action_string(self, **kwargs):
        return "Linking"

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

    def get_parameters_string(self, **kwargs):
        return self.get_output_prefix() + self.simulation_project.dynamic_libraries[0] + self.get_output_suffix() + self.get_output_extension()

    def get_input_files(self):
        return flatten(map(lambda compile_task: compile_task.get_output_files(), self.compile_tasks))

    def get_output_files(self):
        output_folder = self.get_output_folder()
        return [os.path.join(output_folder, self.get_output_prefix() + self.simulation_project.dynamic_libraries[0] + self.get_output_suffix() + self.get_output_extension())]

    def get_arguments(self):
        cfg = self.makefile_inc_config
        sp = self.simulation_project
        input_files = self.get_input_files()

        # Resolve used project library paths
        used_lib_paths = []
        used_lib_names = []
        for used_project_name in sp.used_projects:
            used_proj = get_simulation_project(used_project_name, None)
            lib_path = used_proj.get_library_folder_full_path()
            if lib_path:
                used_lib_paths.append(lib_path)
            if used_proj.dynamic_libraries:
                used_lib_names.append(used_proj.dynamic_libraries[0])

        extra_ldflags = sp.extra_ldflags if hasattr(sp, 'extra_ldflags') else []

        if self.type == "executable":
            if cfg:
                import shlex
                ldflags = shlex.split(cfg.ldflags)
                all_env_libs = shlex.split(cfg.all_env_libs)
                kernel_libs = shlex.split(cfg.kernel_libs)
                sys_libs = shlex.split(cfg.sys_libs)
                oppmain_lib = shlex.split(cfg.oppmain_lib)
                cxx = cfg.cxx.split()[-1] if "ccache" in cfg.cxx else cfg.cxx
            else:
                ldflags = ["-fuse-ld=lld", "-Wl,--export-dynamic"]
                all_env_libs = ["-loppcmdenv", "-loppenvir", "-loppqtenv", "-loppenvir", "-lopplayout"]
                kernel_libs = ["-loppsim"]
                sys_libs = ["-lstdc++"]
                oppmain_lib = ["-loppmain"]
                cxx = "clang++"

            return [cxx,
                    *ldflags,
                    *[f"-L{p}" for p in used_lib_paths],
                    *[f"-L{p}" for p in sp.external_library_folders],
                    "-o", self.get_output_files()[0],
                    *input_files,
                    *[f"-Wl,-rpath,{p}" for p in used_lib_paths],
                    *oppmain_lib,
                    *all_env_libs,
                    *kernel_libs,
                    *[f"-l{n}" for n in used_lib_names],
                    *[f"-l{lib}" for lib in sp.external_libraries],
                    *self.feature_ldflags,
                    *extra_ldflags,
                    *sys_libs]

        elif self.type == "dynamic library":
            if cfg:
                import shlex
                shlib_ld_parts = shlex.split(cfg.shlib_ld)
                ldflags = shlex.split(cfg.ldflags)
                kernel_libs = shlex.split(cfg.kernel_libs)
                sys_libs = shlex.split(cfg.sys_libs)
                as_needed_off = cfg.as_needed_off
                whole_archive_on = cfg.whole_archive_on
                whole_archive_off = cfg.whole_archive_off
            else:
                shlib_ld_parts = ["clang++", "-shared", "-fPIC"]
                ldflags = ["-fuse-ld=lld", "-Wl,--export-dynamic"]
                kernel_libs = ["-loppsim"]
                sys_libs = ["-lstdc++"]
                as_needed_off = "-Wl,--no-as-needed"
                whole_archive_on = "-Wl,--whole-archive"
                whole_archive_off = "-Wl,--no-whole-archive"

            return [*shlib_ld_parts,
                    *ldflags,
                    *[f"-L{p}" for p in used_lib_paths],
                    *[f"-L{p}" for p in sp.external_library_folders],
                    "-o", self.get_output_files()[0],
                    *input_files,
                    as_needed_off,
                    whole_archive_on,
                    whole_archive_off,
                    *[f"-Wl,-rpath,{p}" for p in used_lib_paths],
                    "-loppenvir" + (cfg.debug_suffix if cfg else ""),
                    *kernel_libs,
                    *[f"-l{n}" for n in used_lib_names],
                    *[f"-l{lib}" for lib in sp.external_libraries],
                    *self.feature_ldflags,
                    *extra_ldflags,
                    *sys_libs]

        else:
            ar_cr = cfg.ar_cr if cfg else "ar cr"
            return [*ar_cr.split(),
                    self.get_output_files()[0],
                    *input_files]
