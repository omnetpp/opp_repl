"""
Build the OMNeT++ source tree using per-file ``opp_repl`` tasks.

This is a task-based equivalent of running ``make`` in an OMNeT++ source
checkout. Source-file discovery is by globbing each component's ``src/`` dir,
and compile/link flags come from the project's evaluated ``Makefile.inc``
(via :py:class:`MakefileIncConfig <opp_repl.simulation.makefile_vars.MakefileIncConfig>`).

The main entry point is :py:func:`build_omnetpp_using_tasks`.
"""

import glob
import logging
import multiprocessing
import os
import re
import shlex

from opp_repl.common.compile import *
from opp_repl.common.task import *

_logger = logging.getLogger(__name__)


class _RecursiveBuildTasks(MultipleTasks):
    """
    ``MultipleTasks`` variant whose ``is_up_to_date()`` is the conjunction of
    its children's. Lets the wrapper skip the whole subtree (and all per-child
    log output) once everything is built.
    """

    def __init__(self, multiple_task_results_class=MultipleBuildTaskResults, **kwargs):
        super().__init__(multiple_task_results_class=multiple_task_results_class, **kwargs)

    def is_up_to_date(self):
        return bool(self.tasks) and all(t.is_up_to_date() for t in self.tasks)


def _omnetpp_output_folder(makefile_inc_config, component, mode):
    if makefile_inc_config and makefile_inc_config.configname:
        return f"out/{makefile_inc_config.configname}/src/{component}"
    return f"out/clang-{mode}/src/{component}"


def _split(value):
    return shlex.split(value) if value else []


# ---------------------------------------------------------------------------
# Derived task classes for OMNeT++ self-build
# ---------------------------------------------------------------------------

class OmnetppProjectCppCompileTask(CppCompileTask):
    """
    Compiles one C/C++ source file from an OMNeT++ component, using flags
    derived from the project's ``Makefile.inc``.
    """

    def __init__(self, omnetpp_project=None, component=None, source_file=None,
                 mode="release", makefile_inc_config=None, extra_cflags=None,
                 extra_defines=None, is_c=False, **kwargs):
        self.omnetpp_project = omnetpp_project
        self.component = component
        self.source_file = source_file
        self.mode = mode
        self.makefile_inc_config = makefile_inc_config
        self.is_c = is_c

        cfg = makefile_inc_config
        compiler = _split(cfg.cc if is_c else cfg.cxx) if cfg else (["cc"] if is_c else ["c++"])

        # Filter out -MF from the flags since we set it ourselves
        from opp_repl.simulation.build import _filter_mf_flags
        cflags = _filter_mf_flags(_split(cfg.cflags)) if cfg else []
        cxxflags = [] if is_c else _split(cfg.cxxflags) if cfg else []

        omnetpp_root = omnetpp_project.get_root_path()
        include_dir = cfg.omnetpp_incl_dir if cfg else os.path.join(omnetpp_root, "include")
        src_dir = cfg.omnetpp_src_dir if (cfg and cfg.omnetpp_src_dir) else os.path.join(omnetpp_root, "src")
        include_dirs = [
            os.path.join(omnetpp_root, "src", component),  # component-local headers (for <yxml.h>, ui_*.h, moc_*.cpp)
            include_dir,
            src_dir,
            os.path.join(include_dir, "omnetpp"),  # for generated msg headers (sim_std_m.h, etc.)
        ]

        output_folder = _omnetpp_output_folder(cfg, component, mode)
        obj_name = re.sub(r"\.(cc|cpp|c\+\+|cxx|c)$", ".o", os.path.basename(source_file))
        output_file = os.path.join(output_folder, obj_name)
        dependency_file = f"{output_file}.d"

        defines = list(extra_defines or [])

        super().__init__(
            working_dir=omnetpp_root,
            compiler=compiler,
            cxxflags=cxxflags,
            cflags=cflags,
            defines=defines,
            include_dirs=include_dirs,
            input_file=source_file,
            output_file=output_file,
            dependency_file=dependency_file,
            extra_args=list(extra_cflags or []),
            **kwargs,
        )

    def get_parameters_string(self, **kwargs):
        return self.source_file


class OmnetppProjectLinkTask(LinkTask):
    """
    Links one OMNeT++ library or executable from a set of object files.
    """

    def __init__(self, omnetpp_project=None, component=None, library_name=None,
                 is_executable=False, mode="release", makefile_inc_config=None,
                 compile_tasks=None, extra_libraries=None, **kwargs):
        self.omnetpp_project = omnetpp_project
        self.component = component
        self.library_name = library_name
        self.is_executable = is_executable
        self.mode = mode
        self.makefile_inc_config = makefile_inc_config
        self.compile_tasks = compile_tasks or []

        cfg = makefile_inc_config
        omnetpp_root = omnetpp_project.get_root_path()

        if cfg:
            debug_suffix = cfg.debug_suffix
            shared_ext = cfg.shared_lib_suffix
            exe_ext = cfg.exe_suffix
            lib_prefix = cfg.lib_prefix
            lib_dir = cfg.omnetpp_lib_dir
            bin_dir = cfg.omnetpp_bin_dir or os.path.join(omnetpp_root, "bin")
            sys_libs = _split(cfg.sys_libs)
        else:
            debug_suffix = "_dbg" if mode == "debug" else ""
            shared_ext = ".so"
            exe_ext = ""
            lib_prefix = "lib"
            lib_dir = os.path.join(omnetpp_root, "lib")
            bin_dir = os.path.join(omnetpp_root, "bin")
            sys_libs = ["-lstdc++"]

        input_files = flatten(map(lambda t: t.get_output_files(), self.compile_tasks))

        if is_executable:
            linker = _split(cfg.cxx) if cfg else ["c++"]
            ldflags = _split(cfg.ldflags) if cfg else []
            output_file = os.path.join(bin_dir, library_name + debug_suffix + exe_ext)
            libraries = [*(extra_libraries or []), *sys_libs]
            super().__init__(
                working_dir=omnetpp_root,
                linker=linker,
                ldflags=ldflags,
                input_files=input_files,
                output_file=output_file,
                libraries=libraries,
                library_dirs=[lib_dir],
                rpath_dirs=[lib_dir],
                type="executable",
                **kwargs,
            )
        else:
            linker = _split(cfg.shlib_ld) if cfg else ["c++", "-shared", "-fPIC"]
            ldflags = _split(cfg.ldflags) if cfg else []
            output_file = os.path.join(lib_dir, lib_prefix + library_name + debug_suffix + shared_ext)
            libraries = [*(extra_libraries or []), *sys_libs]
            super().__init__(
                working_dir=omnetpp_root,
                linker=linker,
                ldflags=ldflags,
                input_files=input_files,
                output_file=output_file,
                libraries=libraries,
                library_dirs=[lib_dir],
                rpath_dirs=[lib_dir],
                type="shared",
                **kwargs,
            )

    def get_parameters_string(self, **kwargs):
        return os.path.basename(self.output_file)


class OmnetppProjectCopyBinaryTask(CopyBinaryTask):
    """
    Copies one OMNeT++-built file to its install location (e.g. a script from
    ``src/utils`` into ``bin/``).
    """

    def __init__(self, omnetpp_project=None, source_file=None, target_file=None,
                 postprocess_command=None, **kwargs):
        self.omnetpp_project = omnetpp_project
        super().__init__(
            working_dir=omnetpp_project.get_root_path(),
            source_file=source_file,
            target_file=target_file,
            postprocess_command=postprocess_command,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Component data model
# ---------------------------------------------------------------------------

# Each entry describes one OMNeT++ component. Order matters: later components
# may link against earlier ones (dependency order).
#
# Fields:
#   name:             directory name under src/
#   library_name:     base name of the library (without lib prefix / suffix);
#                     None for header-only / non-library components (utils)
#   define:           the EXPORT macro to pass when building the shared lib
#   subdirs:          additional source subdirectories to include
#   excludes:         basenames of .cc files to exclude (tool main files)
#   conditional_var:  None or makefile_inc_config attr name (e.g. "with_qtenv")
#                     to gate the whole component
#   c_files:          .c (not .cc) files to compile
#   tools:            executables built from a single .cc plus the component lib
#   extra_libraries:  additional libraries built within this component
#                     (e.g. ``oppmain`` in envir)
#   generators:       list of generator specs that run before compile. Each is
#                     a dict with ``kind`` in ("yacc", "lex", "perl", "msgc",
#                     "stringify", "script") plus tool-specific fields.
#                     The special string ``"qtenv-dynamic"`` triggers globbing
#                     of *.ui / *.h / *.qrc for moc/uic/rcc.
#   extra_compile_sources:
#                     generated .cc files (component-relative basenames) to be
#                     added to the compile list — must match what `generators`
#                     produces.
OMNETPP_COMPONENTS = [
    {
        "name": "utils",
        "library_name": None,
        "define": None,
        "c_files": [],
    },
    {
        "name": "common",
        "library_name": "oppcommon",
        "define": "COMMON_EXPORT",
        "c_files": ["sqlite3.c", "yxml.c"],
        "generators": [
            {"kind": "yacc", "input": "expression.y",
             "outputs": ["expression.tab.cc", "expression.tab.h"],
             "flags": ["-o", "expression.tab.cc", "--defines=expression.tab.h",
                       "-p", "expressionyy", "-d"]},
            {"kind": "lex", "input": "expression.lex",
             "outputs": ["expression.lex.cc", "expression.lex.h"],
             "flags": ["-oexpression.lex.cc", "--header-file=expression.lex.h",
                       "-Pexpressionyy"]},
            {"kind": "yacc", "input": "matchexpression.y",
             "outputs": ["matchexpression.tab.cc", "matchexpression.tab.h"],
             "flags": ["-o", "matchexpression.tab.cc", "--no-lines",
                       "--defines=matchexpression.tab.h",
                       "-p", "matchexpressionyy", "-d"]},
        ],
        "extra_compile_sources": [
            "expression.tab.cc", "expression.lex.cc", "matchexpression.tab.cc",
        ],
    },
    {
        "name": "nedxml",
        "library_name": "oppnedxml",
        "define": "NEDXML_EXPORT",
        "excludes": ["opp_nedtool.cc", "opp_msgtool.cc"],
        "c_files": [],
        "tools": [
            {"basename": "opp_nedtool", "source": "opp_nedtool.cc"},
            {"basename": "opp_msgtool", "source": "opp_msgtool.cc"},
        ],
        "generators": [
            {"kind": "perl", "script": "dtdclassgen.pl",
             "dtd_kind": "ned",
             "outputs": [
                 "nedelements.cc", "nedelements.h",
                 "neddtdvalidator.cc", "neddtdvalidator.h",
                 "nedvalidator.cc", "nedvalidator.h",
             ]},
            {"kind": "perl", "script": "dtdclassgen.pl",
             "dtd_kind": "msg",
             "outputs": [
                 "msgelements.cc", "msgelements.h",
                 "msgdtdvalidator.cc", "msgdtdvalidator.h",
                 "msgvalidator.cc", "msgvalidator.h",
             ]},
            {"kind": "yacc", "input": "ned2.y",
             "outputs": ["ned2.tab.cc", "ned2.tab.h"],
             "flags": ["-o", "ned2.tab.cc", "--defines=ned2.tab.h",
                       "-p", "ned2yy", "-d"]},
            {"kind": "lex", "input": "ned2.lex",
             "outputs": ["ned2.lex.cc", "ned2.lex.h"],
             "flags": ["-oned2.lex.cc", "--header-file=ned2.lex.h", "-Pned2yy"]},
            {"kind": "yacc", "input": "msg2.y",
             "outputs": ["msg2.tab.cc", "msg2.tab.h"],
             "flags": ["-o", "msg2.tab.cc", "--defines=msg2.tab.h",
                       "-p", "msg2yy", "-d"]},
            {"kind": "lex", "input": "msg2.lex",
             "outputs": ["msg2.lex.cc", "msg2.lex.h"],
             "flags": ["-omsg2.lex.cc", "--header-file=msg2.lex.h", "-Pmsg2yy"]},
            {"kind": "stringify", "input": "../sim/sim_std.msg",
             "output": "sim_std_msg.cc",
             "varname": "SIM_STD_DEFINITIONS",
             "namespace": "omnetpp::nedxml"},
            {"kind": "copy_script", "source": "opp_msgc", "target_basename": "opp_msgc"},
        ],
        "extra_compile_sources": [
            "nedelements.cc", "neddtdvalidator.cc", "nedvalidator.cc",
            "msgelements.cc", "msgdtdvalidator.cc", "msgvalidator.cc",
            "ned2.tab.cc", "ned2.lex.cc",
            "msg2.tab.cc", "msg2.lex.cc",
            "sim_std_msg.cc",
        ],
    },
    {
        "name": "layout",
        "library_name": "opplayout",
        "define": "LAYOUT_EXPORT",
        "c_files": [],
    },
    {
        "name": "eventlog",
        "library_name": "oppeventlog",
        "define": "EVENTLOG_EXPORT",
        "excludes": ["opp_eventlogtool.cc"],
        "c_files": [],
        "tools": [
            {"basename": "opp_eventlogtool", "source": "opp_eventlogtool.cc"},
        ],
        "generators": [
            {"kind": "perl", "script": "eventlogentries.pl",
             "extra_inputs": ["eventlogentries.txt"],
             "outputs": [
                 "eventlogentries.csv",
                 "eventlogentries.h", "eventlogentries.cc",
                 "eventlogentryfactory.cc",
             ]},
        ],
        "extra_compile_sources": [
            "eventlogentries.cc", "eventlogentryfactory.cc",
        ],
    },
    {
        "name": "scave",
        "library_name": "oppscave",
        "define": "SCAVE_EXPORT",
        "excludes": ["opp_scavetool.cc"],
        "c_files": [],
        "tools": [
            {"basename": "opp_scavetool", "source": "opp_scavetool.cc"},
        ],
    },
    {
        "name": "sim",
        "library_name": "oppsim",
        "define": "SIM_EXPORT",
        "c_files": [],
        "generators": [
            {"kind": "msgc", "input": "sim_std.msg",
             "outputs": ["sim_std_m.cc", "sim_std_m.h"],
             "install_header_to_include_dir": True},
        ],
        "extra_compile_sources": ["sim_std_m.cc"],
    },
    {
        "name": "envir",
        "library_name": "oppenvir",
        "define": "ENVIR_EXPORT",
        "excludes": ["main.cc"],
        "c_files": [],
        "extra_libraries": [
            {"basename": "oppmain", "source_files": ["main.cc"]},
        ],
        "tools": [
            {"basename": "opp_run", "source": "main.cc", "link_with": "oppmain"},
        ],
        "generators": [
            {"kind": "perl", "script": "eventlogwriter.pl",
             "extra_inputs": ["../eventlog/eventlogentries.txt"],
             "outputs": ["eventlogwriter.cc", "eventlogwriter.h"]},
        ],
        "extra_compile_sources": ["eventlogwriter.cc"],
    },
    {
        "name": "cmdenv",
        "library_name": "oppcmdenv",
        "define": "CMDENV_EXPORT",
        "c_files": [],
    },
    {
        "name": "qtenv",
        "library_name": "oppqtenv",
        "define": "QTENV_EXPORT",
        "c_files": [],
        "conditional_var": "with_qtenv",
        "generators": "qtenv-dynamic",  # handled specially in _build_component_tasks
    },
]


# ---------------------------------------------------------------------------
# Generator-task helpers
# ---------------------------------------------------------------------------

class _StringifyTask(BuildTask):
    """
    Wraps a text file into a C++ source by embedding it as a string literal
    in a named namespace. Mirrors the ``STRINGIFY`` recipe used by
    ``src/nedxml`` to embed ``sim_std.msg`` as a build-time string.
    """

    def __init__(self, working_dir=None, input_file=None, output_file=None,
                 namespace="", varname="", name="STRINGIFY", **kwargs):
        super().__init__(working_dir=working_dir, name=name, **kwargs)
        self.input_file = input_file
        self.output_file = output_file
        self.namespace = namespace
        self.varname = varname

    def get_action_string(self, **kwargs):
        return "Stringify"

    def get_parameters_string(self, **kwargs):
        return self.output_file

    def get_input_files(self):
        return [self.input_file]

    def get_output_files(self):
        return [self.output_file]

    def run_protected(self, **kwargs):
        in_path = self._resolve(self.input_file)
        out_path = self._resolve(self.output_file)
        with open(in_path, "r") as f:
            content = f.read()
        ns_open = " ".join(f"namespace {p} {{" for p in self.namespace.split("::") if p)
        ns_close = " ".join("}" for p in self.namespace.split("::") if p)
        body = (
            "//\n// THIS IS A GENERATED FILE, DO NOT EDIT!\n//\n\n"
            f"{ns_open} const char *{self.varname} = R\"ENDMARK(\n"
            f"{content}\n)ENDMARK\"; {ns_close}\n"
        )
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            f.write(body)
        return self.task_result_class(task=self, result="DONE")


class _MsgcWithHeaderInstallTask(MsgCompileTask):
    """
    Runs ``opp_msgc`` and then moves the produced ``*_m.h`` into
    ``$(OMNETPP_INCL_DIR)/omnetpp/`` — needed for ``sim/sim_std.msg``.
    """

    def __init__(self, header_install_path=None, header_local_name=None, **kwargs):
        super().__init__(**kwargs)
        self.header_install_path = header_install_path
        self.header_local_name = header_local_name

    def get_output_files(self):
        outs = list(super().get_output_files())
        # Replace the local header path with the installed location so that
        # is_up_to_date checks see the canonical output.
        return [self.header_install_path if o == self.header_local_name else o
                for o in outs]

    def run_protected(self, **kwargs):
        result = super().run_protected(**kwargs)
        if result.result != "DONE":
            return result
        local_header = self._resolve(self.header_local_name)
        target_header = self._resolve(self.header_install_path)
        if os.path.exists(local_header):
            os.makedirs(os.path.dirname(target_header), exist_ok=True)
            import shutil
            if os.path.exists(target_header):
                os.remove(target_header)
            shutil.move(local_header, target_header)
        return result


def _component_src_dir(omnetpp_root, component_name):
    return os.path.join(omnetpp_root, "src", component_name)


def _build_generator_tasks(omnetpp_project, component, cfg, mode):
    """
    Return a list of generator tasks for one component (yacc/lex/perl/msgc/
    stringify/script-copy). Component sources are generated in-place under
    ``src/<component>/`` so subsequent compile tasks pick them up.
    """
    name = component["name"]
    omnetpp_root = omnetpp_project.get_root_path()
    src_dir = _component_src_dir(omnetpp_root, name)
    gens = component.get("generators")
    if not gens:
        return []
    if gens == "qtenv-dynamic":
        return _build_qtenv_generator_tasks(omnetpp_project, cfg)

    tasks = []
    for spec in gens:
        kind = spec["kind"]
        if kind == "yacc":
            yacc = cfg.yacc.strip() if cfg and cfg.yacc else "bison"
            tasks.append(YaccTask(
                working_dir=src_dir,
                yacc=yacc,
                flags=list(spec.get("flags", [])),
                input_file=spec["input"],
                output_files=list(spec["outputs"]),
                name=f"{name}: {os.path.basename(spec['input'])}",
            ))
        elif kind == "lex":
            lex = cfg.lex.strip() if cfg and cfg.lex else "flex"
            tasks.append(LexTask(
                working_dir=src_dir,
                lex=lex,
                flags=list(spec.get("flags", [])),
                input_file=spec["input"],
                output_files=list(spec["outputs"]),
                name=f"{name}: {os.path.basename(spec['input'])}",
            ))
        elif kind == "perl":
            perl = cfg.perl.strip() if cfg and cfg.perl else "perl"
            extra_inputs = list(spec.get("extra_inputs", []))
            script_args = list(spec.get("script_args", []))
            if "dtd_kind" in spec:
                # dtdclassgen.pl takes a DTD path + a kind tag
                dtd_kind = spec["dtd_kind"]
                dtd_path = os.path.join(omnetpp_root, "doc", "etc", f"{dtd_kind}2.dtd")
                script_args = [dtd_path, dtd_kind]
                extra_inputs.append(dtd_path)
            tasks.append(PerlGenerateTask(
                working_dir=src_dir,
                perl=perl,
                script=spec["script"],
                script_args=script_args,
                input_files=[spec["script"], *extra_inputs],
                output_files=list(spec["outputs"]),
                name=f"{name}: {spec['script']}",
            ))
        elif kind == "msgc":
            msgc_path = os.path.join(omnetpp_root, "bin", "opp_msgc")
            install_header = spec.get("install_header_to_include_dir", False)
            outputs = list(spec["outputs"])
            if install_header and cfg:
                # Mark the .h file as living in <incl>/omnetpp/<basename>
                header_name = next((o for o in outputs if o.endswith(".h")), None)
                if header_name:
                    install_path = os.path.join(cfg.omnetpp_incl_dir, "omnetpp", header_name)
                    tasks.append(_MsgcWithHeaderInstallTask(
                        working_dir=src_dir,
                        msgc=msgc_path,
                        flags=["--msg6"],
                        input_file=spec["input"],
                        output_files=outputs,
                        header_install_path=install_path,
                        header_local_name=header_name,
                        name=f"{name}: {spec['input']}",
                    ))
                    continue
            tasks.append(MsgCompileTask(
                working_dir=src_dir,
                msgc=msgc_path,
                flags=["--msg6"],
                input_file=spec["input"],
                output_files=outputs,
                name=f"{name}: {spec['input']}",
            ))
        elif kind == "stringify":
            tasks.append(_StringifyTask(
                working_dir=src_dir,
                input_file=spec["input"],
                output_file=spec["output"],
                namespace=spec.get("namespace", ""),
                varname=spec.get("varname", "TEXT"),
                name=f"{name}: stringify {os.path.basename(spec['input'])}",
            ))
        elif kind == "copy_script":
            # Copy a shell-script tool (e.g. opp_msgc) to bin/
            bin_dir = (cfg.omnetpp_bin_dir if cfg and cfg.omnetpp_bin_dir
                       else os.path.join(omnetpp_root, "bin"))
            source = os.path.join("src", name, spec["source"])
            target = os.path.relpath(os.path.join(bin_dir, spec["target_basename"]), omnetpp_root)
            tasks.append(OmnetppProjectCopyBinaryTask(
                omnetpp_project=omnetpp_project,
                source_file=source,
                target_file=target,
                postprocess_command=["chmod", "+x"],
                name=f"{name}: install {spec['target_basename']}",
            ))
        else:
            raise ValueError(f"Unknown generator kind: {kind}")
    return tasks


def _build_qtenv_generator_tasks(omnetpp_project, cfg):
    """Glob qtenv's *.ui / *.h / *.qrc and create uic/moc/rcc tasks."""
    omnetpp_root = omnetpp_project.get_root_path()
    src_dir = _component_src_dir(omnetpp_root, "qtenv")
    if not os.path.isdir(src_dir):
        return []
    tasks = []
    moc = cfg.moc.strip() if cfg and cfg.moc else "moc"
    uic = cfg.uic.strip() if cfg and cfg.uic else "uic"
    rcc = cfg.rcc.strip() if cfg and cfg.rcc else "rcc"

    # uic: <name>.ui -> ui_<name>.h
    for ui in sorted(glob.glob(os.path.join(src_dir, "*.ui"))):
        base = os.path.splitext(os.path.basename(ui))[0]
        out = f"ui_{base}.h"
        tasks.append(UicTask(
            working_dir=src_dir, uic=uic,
            input_file=os.path.basename(ui), output_file=out,
            name=f"qtenv: uic {os.path.basename(ui)}",
        ))

    # moc: <name>.h -> moc_<name>.cpp (skip generated ui_*.h)
    for hdr in sorted(glob.glob(os.path.join(src_dir, "*.h"))):
        base = os.path.basename(hdr)
        if base.startswith("ui_"):
            continue
        stem = os.path.splitext(base)[0]
        out = f"moc_{stem}.cpp"
        tasks.append(MocTask(
            working_dir=src_dir, moc=moc,
            flags=["--no-notes"],
            input_file=base, output_file=out,
            name=f"qtenv: moc {base}",
        ))

    # rcc: <name>.qrc -> qrc_<name>.cpp
    # icons_dark.qrc is generated from icons.qrc + dark icons; we skip the
    # dark-icon generation step and just rcc whatever .qrc files exist.
    for qrc in sorted(glob.glob(os.path.join(src_dir, "*.qrc"))):
        base = os.path.basename(qrc)
        stem = os.path.splitext(base)[0]
        out = f"qrc_{stem}.cpp"
        tasks.append(RccTask(
            working_dir=src_dir, rcc=rcc,
            flags=["-name", stem],
            input_file=base, output_file=out,
            name=f"qtenv: rcc {base}",
        ))
    return tasks


def _qtenv_extra_compile_sources(omnetpp_project):
    """Return list of moc_*.cpp / qrc_*.cpp sources for qtenv compile."""
    omnetpp_root = omnetpp_project.get_root_path()
    src_dir = _component_src_dir(omnetpp_root, "qtenv")
    if not os.path.isdir(src_dir):
        return []
    extras = []
    for hdr in sorted(glob.glob(os.path.join(src_dir, "*.h"))):
        base = os.path.basename(hdr)
        if base.startswith("ui_"):
            continue
        stem = os.path.splitext(base)[0]
        extras.append(f"moc_{stem}.cpp")
    for qrc in sorted(glob.glob(os.path.join(src_dir, "*.qrc"))):
        stem = os.path.splitext(os.path.basename(qrc))[0]
        extras.append(f"qrc_{stem}.cpp")
    return extras


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

_STALE_CC_RE = re.compile(r"^lex\..*yy\.cc$")


def _is_stale_generated_cc(basename, expected_generated):
    """
    True if *basename* looks like a leftover generated file (default flex
    output, stray ``.tab.cc`` from a deleted yacc rule, etc.) and isn't on
    the component's expected-generated-sources list.
    """
    if basename in expected_generated:
        return False
    if _STALE_CC_RE.match(basename):
        return True
    if basename.endswith(".tab.cc"):
        return True
    return False


def _glob_component_cc_files(omnetpp_root, component, extra_subdirs=(), expected_generated=()):
    """Return all *.cc files relative to omnetpp_root for a given component.

    Skips leftover build artifacts from prior incompatible builds (e.g.
    ``lex.<prefix>yy.cc`` default flex output, stray ``*.tab.cc`` files
    that aren't on the canonical generator output list).
    """
    base = os.path.join(omnetpp_root, "src", component)
    expected = set(expected_generated)
    files = []
    for f in sorted(glob.glob(os.path.join(base, "*.cc"))):
        if _is_stale_generated_cc(os.path.basename(f), expected):
            continue
        files.append(f)
    for sub in extra_subdirs:
        for f in sorted(glob.glob(os.path.join(base, sub, "*.cc"))):
            if _is_stale_generated_cc(os.path.basename(f), expected):
                continue
            files.append(f)
    return [os.path.relpath(f, omnetpp_root) for f in files]


def _glob_component_c_files(omnetpp_root, component, c_basenames):
    base = os.path.join(omnetpp_root, "src", component)
    return [os.path.relpath(os.path.join(base, name), omnetpp_root)
            for name in c_basenames
            if os.path.exists(os.path.join(base, name))]


def _component_extra_subdirs(component, makefile_inc_config):
    """Conditional subdirectories for a component (netbuilder, parsim, etc.)."""
    if component["name"] == "sim":
        extras = []
        if makefile_inc_config and makefile_inc_config.with_netbuilder:
            extras.append("netbuilder")
        if makefile_inc_config and makefile_inc_config.with_parsim:
            extras.append("parsim")
        return extras
    return list(component.get("subdirs", []))


def _component_extra_cflags(component, makefile_inc_config):
    """Per-component extra compile flags (warnings, includes, feature flags)."""
    cfg = makefile_inc_config
    name = component["name"]
    flags = []
    if name == "common":
        flags += ["-Wno-unused-function"]
        if cfg:
            flags += _split(cfg.libxml_cflags)
    if name == "nedxml" and cfg:
        flags += _split(cfg.libxml_cflags)
    if name == "scave" and cfg:
        flags += ["-DTHREADED"]
        flags += _split(cfg.pthread_cflags)
    if name == "sim":
        flags += ["-Wno-unused-function"]
        if cfg:
            if cfg.with_python:
                flags += _split(cfg.python_embed_cflags)
            flags += _split(cfg.akaroa_cflags)
    if name == "envir" and cfg:
        flags += _split(cfg.akaroa_cflags)
        flags += [
            f'-DSHARED_LIB_SUFFIX="{cfg.shared_lib_suffix}"',
            f'-DOMNETPP_IMAGE_PATH="{cfg.omnetpp_image_path}"',
            f'-DLIBSUFFIX="{cfg.debug_suffix}"',
        ]
        if cfg.with_parsim:
            flags += _split(cfg.mpi_cflags)
    if name == "qtenv" and cfg:
        flags += _split(cfg.qt_cflags)
        flags += ["-Wno-deprecated-declarations",
                  "-Wno-ignored-attributes",
                  "-Wno-inconsistent-missing-override"]
    return flags


def _component_extra_defines(component, makefile_inc_config):
    """Per-component extra preprocessor defines (besides the EXPORT macro)."""
    cfg = makefile_inc_config
    name = component["name"]
    defines = []
    if name == "common" and cfg and cfg.with_backtrace:
        defines.append("-DWITH_BACKTRACE")
    if name == "qtenv":
        defines += ["-DUNICODE", "-DQT_NO_KEYWORDS",
                    "-DQT_OPENGL_LIB", "-DQT_OPENGLWIDGETS_LIB",
                    "-DQT_PRINTSUPPORT_LIB", "-DQT_WIDGETS_LIB",
                    "-DQT_GUI_LIB", "-DQT_CORE_LIB"]
    return defines


# Per-component dependency on previously-built OMNeT++ libraries (mapped to
# ``-l<lib>$D`` at link time). Mirrors the IMPLIBS lines in each component's
# Makefile.
_COMPONENT_LIB_DEPS = {
    "common":   [],
    "nedxml":   ["oppcommon"],
    "layout":   ["oppcommon"],
    "eventlog": ["oppcommon"],
    "scave":    ["oppcommon"],
    "sim":      ["oppcommon"],
    "envir":    ["oppsim", "oppnedxml", "oppcommon"],
    "cmdenv":   ["oppsim", "oppenvir", "oppcommon"],
    "qtenv":    ["oppsim", "oppenvir", "opplayout", "oppcommon"],
}


def _component_extra_libraries(component, makefile_inc_config):
    """
    Per-component extra link tokens. Each entry is already in linker form —
    ``-l<name>``, ``-L<path>``, or another raw ``ldflags`` token — so callers
    can splat the list directly into the link command line.
    """
    cfg = makefile_inc_config
    name = component["name"]
    debug_suffix = cfg.debug_suffix if cfg else ""

    libs = [f"-l{dep}{debug_suffix}" for dep in _COMPONENT_LIB_DEPS.get(name, [])]

    if not cfg:
        return libs

    if name == "common":
        libs += _split(cfg.libxml_libs)
        if cfg.with_backtrace:
            libs += _split(cfg.backward_ldflags)
    if name == "nedxml":
        libs += _split(cfg.libxml_libs)
    if name == "scave":
        libs += _split(cfg.pthread_libs)
    if name == "sim" and cfg.with_python:
        libs += _split(cfg.python_embed_ldflags)
    if name == "qtenv":
        libs += _split(cfg.qt_libs)
    if name == "envir" and cfg.with_parsim:
        libs += _split(cfg.mpi_libs)
    return [l for l in libs if l]


def _strip_lflag(arg):
    """Convert ``-lfoo`` to ``foo``; pass other tokens through unchanged."""
    return arg[2:] if arg.startswith("-l") else arg


def _build_component_tasks(omnetpp_project, component, mode, makefile_inc_config, concurrent):
    """Build the task graph for a single OMNeT++ component."""
    cfg = makefile_inc_config
    cvar = component.get("conditional_var")
    if cvar and cfg and not getattr(cfg, cvar, True):
        _logger.info("Skipping component %s (%s=no)", component["name"], cvar)
        return None

    name = component["name"]
    omnetpp_root = omnetpp_project.get_root_path()

    if name == "utils":
        # utils has no library; just copy scripts to bin/
        utils_src = os.path.join(omnetpp_root, "src", "utils")
        copy_tasks = []
        if os.path.isdir(utils_src):
            bin_dir = (cfg.omnetpp_bin_dir if cfg and cfg.omnetpp_bin_dir
                       else os.path.join(omnetpp_root, "bin"))
            for entry in sorted(os.listdir(utils_src)):
                full = os.path.join(utils_src, entry)
                if os.path.isfile(full) and os.access(full, os.X_OK):
                    copy_tasks.append(OmnetppProjectCopyBinaryTask(
                        omnetpp_project=omnetpp_project,
                        source_file=os.path.relpath(full, omnetpp_root),
                        target_file=os.path.relpath(os.path.join(bin_dir, entry), omnetpp_root),
                    ))
        if not copy_tasks:
            return None
        return _RecursiveBuildTasks(
            tasks=copy_tasks,
            name=f"build {name}",
            concurrent=concurrent,
        )

    # Generator tasks (yacc/lex/perl/msgc/stringify/moc/uic/rcc)
    generator_tasks = _build_generator_tasks(omnetpp_project, component, cfg, mode)

    # Compile tasks
    excludes = set(component.get("excludes", []))
    # Also exclude sources reserved for tools/extra libraries
    for tool in component.get("tools", []):
        excludes.add(tool["source"])
    for lib in component.get("extra_libraries", []):
        for src in lib.get("source_files", []):
            excludes.add(src)

    expected_generated = set(component.get("extra_compile_sources", []) or [])
    if component.get("generators") == "qtenv-dynamic":
        expected_generated |= set(_qtenv_extra_compile_sources(omnetpp_project))
    cc_files = _glob_component_cc_files(omnetpp_root, name,
                                        extra_subdirs=_component_extra_subdirs(component, cfg),
                                        expected_generated=expected_generated)
    cc_files = [f for f in cc_files if os.path.basename(f) not in excludes]
    c_files = _glob_component_c_files(omnetpp_root, name, component.get("c_files", []))

    # Add generated sources (.cc / .cpp) declared by the component, plus any
    # qtenv-dynamic moc/qrc outputs. These files do not exist on disk at
    # graph-construction time, so they have to be enumerated explicitly.
    extra_sources = list(component.get("extra_compile_sources", []) or [])
    if component.get("generators") == "qtenv-dynamic":
        extra_sources += _qtenv_extra_compile_sources(omnetpp_project)
    for extra in extra_sources:
        rel = os.path.relpath(os.path.join(omnetpp_root, "src", name, extra), omnetpp_root)
        if rel not in cc_files:
            cc_files.append(rel)

    extra_cflags = _component_extra_cflags(component, cfg)
    extra_defines = []
    if component.get("define"):
        extra_defines.append(f"-D{component['define']}")
    extra_defines += _component_extra_defines(component, cfg)

    compile_tasks = []
    for cc in cc_files:
        compile_tasks.append(OmnetppProjectCppCompileTask(
            omnetpp_project=omnetpp_project,
            component=name,
            source_file=cc,
            mode=mode,
            makefile_inc_config=cfg,
            extra_cflags=extra_cflags,
            extra_defines=extra_defines,
        ))
    for c in c_files:
        compile_tasks.append(OmnetppProjectCppCompileTask(
            omnetpp_project=omnetpp_project,
            component=name,
            source_file=c,
            mode=mode,
            makefile_inc_config=cfg,
            extra_cflags=extra_cflags,
            extra_defines=extra_defines,
            is_c=True,
        ))

    # Library link
    library_name = component.get("library_name")
    extra_libraries = _component_extra_libraries(component, cfg)
    component_tasks = []

    if generator_tasks:
        component_tasks.append(_RecursiveBuildTasks(
            tasks=generator_tasks,
            name=f"generate {name}",
            concurrent=concurrent,
        ))

    if compile_tasks:
        component_tasks.append(_RecursiveBuildTasks(
            tasks=compile_tasks,
            name=f"compile {name}",
            concurrent=concurrent,
        ))

    if library_name and compile_tasks:
        link_task = OmnetppProjectLinkTask(
            omnetpp_project=omnetpp_project,
            component=name,
            library_name=library_name,
            is_executable=False,
            mode=mode,
            makefile_inc_config=cfg,
            compile_tasks=compile_tasks,
            extra_libraries=extra_libraries,
        )
        component_tasks.append(link_task)

    # Extra static-like libraries (e.g. oppmain in envir)
    for extra_lib in component.get("extra_libraries", []):
        extra_sources = extra_lib["source_files"]
        extra_compile_tasks = []
        for src in extra_sources:
            src_rel = os.path.relpath(os.path.join(omnetpp_root, "src", name, src), omnetpp_root)
            extra_compile_tasks.append(OmnetppProjectCppCompileTask(
                omnetpp_project=omnetpp_project,
                component=name,
                source_file=src_rel,
                mode=mode,
                makefile_inc_config=cfg,
                extra_cflags=extra_cflags,
                extra_defines=extra_defines,
            ))
        if extra_compile_tasks:
            component_tasks.append(_RecursiveBuildTasks(
                tasks=extra_compile_tasks,
                name=f"compile {extra_lib['basename']}",
                concurrent=concurrent,
            ))
            component_tasks.append(OmnetppProjectLinkTask(
                omnetpp_project=omnetpp_project,
                component=name,
                library_name=extra_lib["basename"],
                is_executable=False,
                mode=mode,
                makefile_inc_config=cfg,
                compile_tasks=extra_compile_tasks,
            ))

    # Tool executables
    for tool in component.get("tools", []):
        tool_src_rel = os.path.relpath(os.path.join(omnetpp_root, "src", name, tool["source"]), omnetpp_root)
        tool_compile_task = OmnetppProjectCppCompileTask(
            omnetpp_project=omnetpp_project,
            component=name,
            source_file=tool_src_rel,
            mode=mode,
            makefile_inc_config=cfg,
            extra_cflags=extra_cflags,
            extra_defines=extra_defines,
        )
        debug_suffix = cfg.debug_suffix if cfg else ""
        tool_link_libs = [f"-l{library_name}{debug_suffix}"] if library_name else []
        if tool.get("link_with"):
            tool_link_libs.insert(0, f"-l{tool['link_with']}{debug_suffix}")
        component_tasks.append(tool_compile_task)
        component_tasks.append(OmnetppProjectLinkTask(
            omnetpp_project=omnetpp_project,
            component=name,
            library_name=tool["basename"],
            is_executable=True,
            mode=mode,
            makefile_inc_config=cfg,
            compile_tasks=[tool_compile_task],
            extra_libraries=tool_link_libs + extra_libraries,
        ))

    if not component_tasks:
        return None
    return _RecursiveBuildTasks(
        tasks=component_tasks,
        name=f"build {name}",
        concurrent=False,  # within a component, ordering matters (compile -> link)
    )


def build_omnetpp(build_mode="makefile", **kwargs):
    """
    Builds OMNeT++ using either :py:func:`build_omnetpp_using_makefile` or
    :py:func:`build_omnetpp_using_tasks`.

    Parameters:
        build_mode (str):
            Specifies the requested build mode. Valid values are
            ``"makefile"`` and ``"task"``.

        kwargs (dict):
            Additional parameters are forwarded to the selected builder.
    """
    if build_mode == "makefile":
        build_function = build_omnetpp_using_makefile
    elif build_mode == "task":
        build_function = build_omnetpp_using_tasks
    else:
        raise Exception(f"Unknown build_mode argument: {build_mode}")
    return build_function(**kwargs)


def build_omnetpp_using_makefile(omnetpp_project=None, mode="release", **kwargs):
    """
    Builds OMNeT++ by running ``make`` in the OMNeT++ root directory.

    Parameters:
        omnetpp_project (:py:class:`OmnetppProject <opp_repl.simulation.project.OmnetppProject>`):
            The OMNeT++ project (installation) to build.

        mode (str):
            Build mode for the output binaries (``release``, ``debug``,
            ``sanitize``, ``coverage``, ``profile``).
    """
    if omnetpp_project is None:
        raise RuntimeError("omnetpp_project is required")
    omnetpp_project.ensure_mounted()
    omnetpp_project.ensure_configured()
    root = omnetpp_project.get_root_path()
    if root is None:
        raise RuntimeError("Cannot build OMNeT++: root path is not set")
    if omnetpp_project.is_build_up_to_date(mode=mode):
        return
    env = omnetpp_project.get_env()
    args = ["make", "MODE=" + mode, "-j", str(multiprocessing.cpu_count())]
    _logger.info("Building OMNeT++ in %s mode at %s started", mode, root)
    if omnetpp_project.opp_env_workspace:
        opp_env_project = omnetpp_project.opp_env_project or omnetpp_project.name
        shell_cmd = "cd " + shlex.quote(root) + " && " + shlex.join(args)
        args = ["opp_env", "-l", "WARN", "run", opp_env_project, "-w", omnetpp_project.opp_env_workspace, "-c", shell_cmd]
        run_command_with_logging(args, error_message="Building OMNeT++ failed")
    else:
        run_command_with_logging(args, cwd=root, env=env, error_message="Building OMNeT++ failed")
    _logger.info("Building OMNeT++ in %s mode at %s ended", mode, root)


# ---------------------------------------------------------------------------
# Clean tasks
# ---------------------------------------------------------------------------

class _CleanFileTask(Task):
    """Delete a single file, paths relative to a base directory."""

    def __init__(self, working_dir=None, file_path=None, name="clean file task", **kwargs):
        super().__init__(name=name, action="Removing", **kwargs)
        self.working_dir = working_dir
        self.file_path = file_path

    def _full_path(self):
        if os.path.isabs(self.file_path):
            return self.file_path
        return os.path.join(self.working_dir, self.file_path)

    def get_description(self):
        return self.file_path

    def get_parameters_string(self, **kwargs):
        return self.file_path

    def is_up_to_date(self):
        return not os.path.exists(self._full_path())

    def run_protected(self, **kwargs):
        full_path = self._full_path()
        if os.path.exists(full_path):
            os.remove(full_path)
        return self.task_result_class(task=self, result="DONE")


class _CleanDirectoryTask(Task):
    """Recursively remove a directory, path relative to a base directory."""

    def __init__(self, working_dir=None, directory_path=None, name="clean directory task", **kwargs):
        super().__init__(name=name, action="Removing", **kwargs)
        self.working_dir = working_dir
        self.directory_path = directory_path

    def _full_path(self):
        if os.path.isabs(self.directory_path):
            return self.directory_path
        return os.path.join(self.working_dir, self.directory_path)

    def get_description(self):
        return self.directory_path

    def get_parameters_string(self, **kwargs):
        return self.directory_path

    def is_up_to_date(self):
        return not os.path.exists(self._full_path())

    def run_protected(self, **kwargs):
        import shutil
        full_path = self._full_path()
        if os.path.exists(full_path):
            shutil.rmtree(full_path)
        return self.task_result_class(task=self, result="DONE")


class _MultipleCleanTasks(MultipleTasks):
    def is_up_to_date(self):
        return bool(self.tasks) and all(t.is_up_to_date() for t in self.tasks)


def _build_component_clean_tasks(omnetpp_project, component, cfg, mode):
    """Return clean tasks for one OMNeT++ component (generated sources +
    installed libraries / executables / scripts). The shared ``out/`` tree is
    cleaned once at the top level, not per component."""
    name = component["name"]
    omnetpp_root = omnetpp_project.get_root_path()
    src_dir = _component_src_dir(omnetpp_root, name)
    cvar = component.get("conditional_var")
    if cvar and cfg and not getattr(cfg, cvar, True):
        return []

    debug_suffix = cfg.debug_suffix if cfg else ""
    shared_ext = cfg.shared_lib_suffix if cfg else ".so"
    exe_ext = cfg.exe_suffix if cfg else ""
    lib_prefix = cfg.lib_prefix if cfg else "lib"
    lib_dir = cfg.omnetpp_lib_dir if cfg else os.path.join(omnetpp_root, "lib")
    bin_dir = (cfg.omnetpp_bin_dir if cfg and cfg.omnetpp_bin_dir
               else os.path.join(omnetpp_root, "bin"))

    tasks = []

    # Generated sources (yacc/lex/perl/msgc/stringify outputs) in src/<comp>/
    gens = component.get("generators")
    if gens == "qtenv-dynamic":
        for out in _qtenv_extra_compile_sources(omnetpp_project):
            tasks.append(_CleanFileTask(working_dir=src_dir, file_path=out))
        # Also remove ui_*.h files which aren't part of extra_compile_sources
        for ui in sorted(glob.glob(os.path.join(src_dir, "*.ui"))):
            stem = os.path.splitext(os.path.basename(ui))[0]
            tasks.append(_CleanFileTask(working_dir=src_dir, file_path=f"ui_{stem}.h"))
    elif gens:
        for spec in gens:
            kind = spec["kind"]
            if kind in ("yacc", "lex", "perl"):
                for out in spec.get("outputs", []):
                    tasks.append(_CleanFileTask(working_dir=src_dir, file_path=out))
            elif kind == "msgc":
                for out in spec.get("outputs", []):
                    tasks.append(_CleanFileTask(working_dir=src_dir, file_path=out))
                # Also clean header installed to include/omnetpp/
                if spec.get("install_header_to_include_dir") and cfg:
                    header_name = next((o for o in spec.get("outputs", []) if o.endswith(".h")), None)
                    if header_name:
                        installed = os.path.join(cfg.omnetpp_incl_dir, "omnetpp", header_name)
                        tasks.append(_CleanFileTask(working_dir=omnetpp_root, file_path=installed))
            elif kind == "stringify":
                tasks.append(_CleanFileTask(working_dir=src_dir, file_path=spec["output"]))
            elif kind == "copy_script":
                target = os.path.join(bin_dir, spec["target_basename"])
                tasks.append(_CleanFileTask(working_dir=omnetpp_root, file_path=target))

    # Installed library (lib/lib<name><D>.so)
    library_name = component.get("library_name")
    if library_name:
        lib_file = os.path.join(lib_dir, lib_prefix + library_name + debug_suffix + shared_ext)
        tasks.append(_CleanFileTask(working_dir=omnetpp_root, file_path=lib_file))

    # Extra libraries (e.g. oppmain)
    for extra_lib in component.get("extra_libraries", []):
        lib_file = os.path.join(lib_dir, lib_prefix + extra_lib["basename"] + debug_suffix + shared_ext)
        tasks.append(_CleanFileTask(working_dir=omnetpp_root, file_path=lib_file))

    # Tool executables (opp_nedtool, opp_msgtool, opp_run, ...)
    for tool in component.get("tools", []):
        exe_file = os.path.join(bin_dir, tool["basename"] + debug_suffix + exe_ext)
        tasks.append(_CleanFileTask(working_dir=omnetpp_root, file_path=exe_file))

    # utils: scripts copied to bin/
    if name == "utils":
        utils_src = os.path.join(omnetpp_root, "src", "utils")
        if os.path.isdir(utils_src):
            for entry in sorted(os.listdir(utils_src)):
                full = os.path.join(utils_src, entry)
                if os.path.isfile(full) and os.access(full, os.X_OK):
                    tasks.append(_CleanFileTask(
                        working_dir=omnetpp_root,
                        file_path=os.path.join(bin_dir, entry),
                    ))

    return tasks


def clean_omnetpp(build_mode="makefile", **kwargs):
    """
    Cleans OMNeT++ using either :py:func:`clean_omnetpp_using_makefile` or
    :py:func:`clean_omnetpp_using_tasks`.

    Parameters:
        build_mode (str):
            ``"makefile"`` (default) runs ``make clean`` in the OMNeT++ tree.
            ``"task"`` removes generated sources, built objects, libraries and
            executables directly.
    """
    if build_mode == "makefile":
        clean_function = clean_omnetpp_using_makefile
    elif build_mode == "task":
        clean_function = clean_omnetpp_using_tasks
    else:
        raise Exception(f"Unknown build_mode argument: {build_mode}")
    return clean_function(**kwargs)


def clean_omnetpp_using_makefile(omnetpp_project=None, mode="release", **kwargs):
    """Run ``make clean`` in the OMNeT++ root for the given mode."""
    if omnetpp_project is None:
        raise RuntimeError("omnetpp_project is required")
    omnetpp_project.ensure_mounted()
    root = omnetpp_project.get_root_path()
    if root is None:
        raise RuntimeError("Cannot clean OMNeT++: root path is not set")
    if not os.path.isfile(os.path.join(root, "Makefile")):
        _logger.info("Cleaning OMNeT++ in %s mode at %s skipped (no Makefile)", mode, root)
        return
    env = omnetpp_project.get_env()
    args = ["make", "MODE=" + mode, "clean"]
    _logger.info("Cleaning OMNeT++ in %s mode at %s started", mode, root)
    if omnetpp_project.opp_env_workspace:
        opp_env_project = omnetpp_project.opp_env_project or omnetpp_project.name
        shell_cmd = "cd " + shlex.quote(root) + " && " + shlex.join(args)
        args = ["opp_env", "-l", "WARN", "run", opp_env_project, "-w", omnetpp_project.opp_env_workspace, "-c", shell_cmd]
        run_command_with_logging(args)
    else:
        run_command_with_logging(args, cwd=root, env=env)
    _logger.info("Cleaning OMNeT++ in %s mode at %s ended", mode, root)


def clean_omnetpp_using_tasks(omnetpp_project=None, mode="release", concurrent=True, **kwargs):
    """
    Clean OMNeT++ using per-file tasks: remove generated sources, the build
    output directory, installed libraries and executables.
    """
    if omnetpp_project is None:
        raise RuntimeError("omnetpp_project is required")
    omnetpp_project.ensure_mounted()
    omnetpp_root = omnetpp_project.get_root_path()
    if omnetpp_root is None:
        raise RuntimeError("Cannot clean OMNeT++: root path is not set")

    try:
        cfg = omnetpp_project.get_makefile_inc_config(mode)
    except Exception:
        cfg = None

    component_tasks = []
    for component in OMNETPP_COMPONENTS:
        comp_tasks = _build_component_clean_tasks(omnetpp_project, component, cfg, mode)
        if comp_tasks:
            component_tasks.append(_MultipleCleanTasks(
                tasks=comp_tasks,
                name=f"clean {component['name']}",
                concurrent=concurrent,
            ))

    # Output directory (out/<configname>/, or all of out/ if no config)
    out_path = f"out/{cfg.configname}" if cfg else "out"
    component_tasks.append(_CleanDirectoryTask(
        working_dir=omnetpp_root, directory_path=out_path,
        name="clean output directory",
    ))

    top_task = _MultipleCleanTasks(
        tasks=component_tasks,
        name=f"clean OMNeT++ ({mode})",
        concurrent=False,
    )
    top_task.log_structure()
    return top_task.run(**kwargs)


def build_omnetpp_using_tasks(omnetpp_project=None, mode="release", concurrent=True, **kwargs):
    """
    Build the OMNeT++ source tree using per-file tasks.

    Parameters:
        omnetpp_project (:py:class:`OmnetppProject <opp_repl.simulation.project.OmnetppProject>`):
            The OMNeT++ project (installation) to build.
        mode (str):
            Build mode: ``release``, ``debug``, ``sanitize``, ``coverage``, ``profile``.
        concurrent (bool):
            Whether per-component compile tasks may run in parallel.

    Returns:
        The result of the top-level :py:class:`MultipleTasks`.
    """
    if omnetpp_project is None:
        raise RuntimeError("omnetpp_project is required")
    omnetpp_project.ensure_mounted()
    omnetpp_project.ensure_configured()

    makefile_inc_config = omnetpp_project.get_makefile_inc_config(mode)

    component_tasks = []
    for component in OMNETPP_COMPONENTS:
        task = _build_component_tasks(omnetpp_project, component, mode, makefile_inc_config, concurrent)
        if task is not None:
            component_tasks.append(task)

    top_task = _RecursiveBuildTasks(
        tasks=component_tasks,
        name=f"build OMNeT++ ({mode})",
        concurrent=False,  # components must be built in dependency order
    )
    top_task.log_structure()
    return top_task.run(**kwargs)
