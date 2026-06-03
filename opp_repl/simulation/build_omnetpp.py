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


class _ToolBuildTasks(_RecursiveBuildTasks):
    """
    ``_RecursiveBuildTasks`` for an OMNeT++ tool executable (opp_nedtool,
    opp_msgtool, opp_eventlogtool, opp_scavetool) where the makefile build
    uses a *combined compile+link* recipe — so a prior ``make`` run leaves
    only ``bin/<tool>`` on disk, with no intermediate ``.o`` for the task
    engine to recognise.

    Overrides ``is_up_to_date()`` to also accept the makefile's artifact:
    if the installed executable exists and is newer than the source ``.cc``,
    declare the whole compile→link chain up-to-date so the task engine
    doesn't redundantly re-compile and re-link.
    """

    def __init__(self, executable_path=None, source_file=None, **kwargs):
        super().__init__(**kwargs)
        self.executable_path = executable_path
        self.source_file = source_file

    def is_up_to_date(self):
        if super().is_up_to_date():
            return True
        if self.executable_path and self.source_file and \
                os.path.exists(self.executable_path) and os.path.exists(self.source_file) and \
                os.path.getmtime(self.executable_path) > os.path.getmtime(self.source_file):
            return True
        return False


def _omnetpp_output_folder(makefile_inc_config, component, mode):
    if makefile_inc_config and makefile_inc_config.configname:
        return f"out/{makefile_inc_config.configname}/src/{component}"
    return f"out/clang-{mode}/src/{component}"


def _split(value):
    return shlex.split(value) if value else []


# ---------------------------------------------------------------------------
# Derived task classes for OMNeT++ self-build
# ---------------------------------------------------------------------------

def _filter_cflags(cfg):
    """Return ``cfg.cflags`` parsed and stripped of the ``-MF <path>`` that we set ourselves."""
    from opp_repl.simulation.build import _filter_mf_flags
    return _filter_mf_flags(_split(cfg.cflags)) if cfg else []


def _build_component_copts_layout(component_name, cfg, mode="release"):
    """
    Reproduce one OMNeT++ component's ``COPTS`` layout from its ``src/<comp>/Makefile``
    so the task-engine compile cmdline matches the makefile one, for ccache reuse.

    Returns a 5-tuple ``(prefix, cflags_extra, middle, late, export_extra)``:

    * ``prefix``       — tokens before ``$(CFLAGS)`` in the component's ``COPTS=`` line
    * ``cflags_extra`` — tokens appended to ``$(CFLAGS)`` via the component's
                         ``DEFINES += ...`` lines (qtenv adds Qt-feature defines this way)
    * ``middle``       — tokens between ``$(CFLAGS)`` and ``$(INCL_FLAGS)``
    * ``late``         — tokens after ``$(INCL_FLAGS)`` in ``COPTS=`` plus all
                         ``COPTS += ...`` additions, in their textual order
    * ``export_extra`` — additional ``EXPORT_MACRO`` tokens beyond ``-D<COMP>_EXPORT``
                         (currently just ``-DSQLITE_API=...`` for ``common``)
    """
    prefix, cflags_extra, middle, late, export_extra = [], [], [], [], []
    if not cfg:
        return prefix, cflags_extra, middle, late, export_extra
    if component_name == "common":
        prefix += ["-Wno-unused-function"]
        middle += _split(cfg.libxml_cflags)
        if cfg.with_backtrace:
            late += ["-DWITH_BACKTRACE"]
        export_extra += ['-DSQLITE_API=__attribute__ ((visibility ("default")))']
    elif component_name == "nedxml":
        middle += _split(cfg.libxml_cflags)
    elif component_name == "scave":
        # `-DTHREADED $(PTHREAD_CFLAGS)` is gated on BUILDING_UILIBS in src/scave/Makefile;
        # the task engine never builds uilibs, so we skip it here too.
        pass
    elif component_name == "sim":
        prefix += ["-Wno-unused-function"]
        if cfg.with_parsim:
            late += _split(cfg.mpi_cflags)
        if cfg.with_python:
            late += _split(cfg.python_embed_cflags)
    elif component_name == "envir":
        middle += _split(cfg.akaroa_cflags)
        late += [
            f'-DSHARED_LIB_SUFFIX="{cfg.shared_lib_suffix}"',
            f'-DOMNETPP_IMAGE_PATH="{cfg.omnetpp_image_path}"',
            f'-DLIBSUFFIX="{cfg.debug_suffix}"',
        ]
        if cfg.with_parsim:
            late += _split(cfg.mpi_cflags)
    elif component_name == "qtenv":
        # qtenv extends `DEFINES` (used inside $(CFLAGS)) with Qt feature flags,
        # so these end up between -DBACKWARD_HAS_DW=1 and $(INCL_FLAGS).
        cflags_extra += [
            "-DUNICODE", "-DQT_NO_KEYWORDS",
            "-DQT_OPENGL_LIB", "-DQT_OPENGLWIDGETS_LIB",
            "-DQT_PRINTSUPPORT_LIB", "-DQT_WIDGETS_LIB",
            "-DQT_GUI_LIB", "-DQT_CORE_LIB",
        ]
        if mode == "release":
            cflags_extra += ["-DQT_NO_DEBUG_OUTPUT"]
        late += _split(cfg.qt_cflags)
        late += [
            "-Wno-deprecated-declarations",
            "-Wno-ignored-attributes",
            "-Wno-inconsistent-missing-override",
        ]
    return prefix, cflags_extra, middle, late, export_extra


# Per-file specializations for sources whose Makefile rule deviates from the
# standard ``$(CXX) -c $(CXXFLAGS) $(COPTS) $(EXPORT_DEFINES) $(IMPORT_DEFINES)``
# layout. Each entry maps ``(component, basename)`` to a dict with optional keys:
#
# * ``extra_pre_copts``     — tokens inserted before ``COPTS`` (e.g. yxml.c's ``-I.``)
# * ``extra_pre_export``    — tokens between ``COPTS`` and ``EXPORT_DEFINES``
#                             (e.g. sqlite3.c's ``-Wno-deprecated-declarations``)
# * ``extra_post_export``   — tokens between ``EXPORT_DEFINES`` and ``IMPORT_DEFINES``
#                             (e.g. sqlite3.c's ``SQLITE_*`` feature defines)
# * ``skip_import_defines`` — drop ``-DOMNETPPLIBS_IMPORT`` (.c files)
_PER_FILE_COMPILE_OVERRIDES = {
    ("common", "sqlite3.c"): {
        "extra_pre_export": ["-Wno-deprecated-declarations"],
        "extra_post_export": [
            "-DSQLITE_THREADSAFE=0",
            "-DSQLITE_OMIT_LOAD_EXTENSION",
            "-DSQLITE_DEFAULT_FOREIGN_KEYS=1",
        ],
        "skip_import_defines": True,
    },
    ("common", "yxml.c"): {
        "extra_pre_copts": ["-I."],
        "skip_import_defines": True,
    },
}


class OmnetppProjectCppCompileTask(CppCompileTask):
    """
    Compiles one C/C++ source file from an OMNeT++ component, using flags
    derived from the project's ``Makefile.inc``.

    The compile is run from ``<root>/src/<component>/`` (mirroring how the
    makefile build invokes ``make`` per component), the source is passed as a
    bare basename, and the argument order matches the per-component
    ``$(CXX) -c $(CXXFLAGS) $(COPTS) $(EXPORT_DEFINES) $(IMPORT_DEFINES)``
    recipe. This lets ccache treat the makefile and task engines as
    interchangeable: build one, clean, build the other → cache hits.
    """

    def __init__(self, omnetpp_project=None, component=None, source_file=None,
                 mode="release", makefile_inc_config=None, is_c=False, **kwargs):
        self.omnetpp_project = omnetpp_project
        self.component = component
        self.source_file = source_file
        self.mode = mode
        self.makefile_inc_config = makefile_inc_config
        self.is_c = is_c

        cfg = makefile_inc_config
        compiler = _split(cfg.cc if is_c else cfg.cxx) if cfg else (["cc"] if is_c else ["c++"])

        omnetpp_root = omnetpp_project.get_root_path()
        component_dir = os.path.join(omnetpp_root, "src", component)

        # Path of the source relative to the component dir — typically just the
        # basename, but sources from a subdir (e.g. sim/parsim) are passed as
        # "parsim/foo.cc" to match the makefile's `%.cc` pattern in that subdir.
        src_abs = source_file if os.path.isabs(source_file) else os.path.join(omnetpp_root, source_file)
        input_basename = os.path.relpath(src_abs, component_dir)

        # Output and dep paths kept absolute (under the shared out tree).
        # Preserve any subdir part of input_basename (e.g. parsim/foo.cc) so the
        # .o lands at out/<configname>/src/<comp>/<subdir>/foo.o, matching the
        # makefile's `$O/%.o: %.cc` pattern that resolves $O = out/.../src/<comp>.
        output_folder_rel = _omnetpp_output_folder(cfg, component, mode)
        output_folder = os.path.join(omnetpp_root, output_folder_rel)
        obj_name = re.sub(r"\.(cc|cpp|c\+\+|cxx|c)$", ".o", input_basename)
        output_file = os.path.join(output_folder, obj_name)
        dependency_file = f"{output_file}.d"

        super().__init__(
            working_dir=component_dir,
            compiler=compiler,
            cxxflags=[] if is_c else _split(cfg.cxxflags) if cfg else [],
            cflags=_filter_cflags(cfg),
            defines=[],
            include_dirs=[],
            input_file=input_basename,
            output_file=output_file,
            dependency_file=dependency_file,
            extra_args=[],
            **kwargs,
        )

    def get_parameters_string(self, **kwargs):
        return self.source_file

    def get_arguments(self):
        cfg = self.makefile_inc_config
        omnetpp_root = self.omnetpp_project.get_root_path()
        include_dir = cfg.omnetpp_incl_dir if cfg else os.path.join(omnetpp_root, "include")
        src_dir = cfg.omnetpp_src_dir if (cfg and cfg.omnetpp_src_dir) else os.path.join(omnetpp_root, "src")
        incl_flags = [f'-I{include_dir}', f'-I{src_dir}']

        prefix, cflags_extra, middle, late, export_extra = _build_component_copts_layout(
            self.component, cfg, self.mode)

        export_defs = []
        comp = next((c for c in OMNETPP_COMPONENTS if c["name"] == self.component), None)
        if comp and comp.get("define"):
            export_defs.append(f'-D{comp["define"]}')
        export_defs += export_extra

        import_defs = []
        if cfg and getattr(cfg, "shared_libs", True):
            import_defs.append("-DOMNETPPLIBS_IMPORT")

        # Per-file special cases (sqlite3.c, yxml.c) bypass the standard layout.
        override = _PER_FILE_COMPILE_OVERRIDES.get((self.component, os.path.basename(self.input_file)))
        if override and override.get("skip_import_defines"):
            import_defs = []

        extra_pre_copts = (override or {}).get("extra_pre_copts", [])
        extra_pre_export = (override or {}).get("extra_pre_export", [])
        extra_post_export = (override or {}).get("extra_post_export", [])

        # _m.cc files (generated message wrappers) need -I include/omnetpp for the
        # installed companion header, placed between COPTS and EXPORT_DEFINES.
        msg_incl = []
        if os.path.basename(self.input_file).endswith("_m.cc") and cfg:
            msg_incl = [f'-I{os.path.join(cfg.omnetpp_incl_dir, "omnetpp")}']

        args = [
            *self.compiler, "-c",
            *self.cxxflags,
            *extra_pre_copts,
            *prefix,
            *self.cflags,
            *cflags_extra,
            *middle,
            *incl_flags,
            *late,
            *msg_incl,
            *extra_pre_export,
            *export_defs,
            *extra_post_export,
            *import_defs,
        ]
        if self.dependency_file:
            args += ["-MF", self.dependency_file]
        args += ["-o", self.output_file, self.input_file]
        return args


class OmnetppProjectLinkTask(LinkTask):
    """
    Links one OMNeT++ library or executable from a set of object files.

    ``library_type`` selects between ``"shared"`` (``.so``, default for
    non-executables), ``"static"`` (``.a`` via ``ar``), and the implicit
    ``"executable"`` (when ``is_executable=True``).
    """

    def __init__(self, omnetpp_project=None, component=None, library_name=None,
                 is_executable=False, library_type="shared", mode="release",
                 makefile_inc_config=None, compile_tasks=None, extra_libraries=None, **kwargs):
        self.omnetpp_project = omnetpp_project
        self.component = component
        self.library_name = library_name
        self.is_executable = is_executable
        self.library_type = library_type
        self.mode = mode
        self.makefile_inc_config = makefile_inc_config
        self.compile_tasks = compile_tasks or []

        cfg = makefile_inc_config
        omnetpp_root = omnetpp_project.get_root_path()

        if cfg:
            debug_suffix = cfg.debug_suffix
            shared_ext = cfg.shared_lib_suffix
            static_ext = getattr(cfg, "a_lib_suffix", ".a") or ".a"
            exe_ext = cfg.exe_suffix
            lib_prefix = cfg.lib_prefix
            lib_dir = cfg.omnetpp_lib_dir
            bin_dir = cfg.omnetpp_bin_dir or os.path.join(omnetpp_root, "bin")
            sys_libs = _split(cfg.sys_libs)
        else:
            debug_suffix = "_dbg" if mode == "debug" else ""
            shared_ext = ".so"
            static_ext = ".a"
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
        elif library_type == "static":
            output_file = os.path.join(lib_dir, lib_prefix + library_name + debug_suffix + static_ext)
            ar = _split(cfg.ar) if cfg and getattr(cfg, "ar", None) else ["ar", "cr"]
            ranlib = _split(cfg.ranlib) if cfg and getattr(cfg, "ranlib", None) else None
            super().__init__(
                working_dir=omnetpp_root,
                input_files=input_files,
                output_file=output_file,
                type="static",
                ar=ar,
                ranlib=ranlib,
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
            # liboppmain is a static archive in src/envir/Makefile (LIBNAME=$(MAINLIBNAME) → .a).
            {"basename": "oppmain", "source_files": ["main.cc"], "link_type": "static"},
        ],
        # NOTE: opp_run is *not* listed as a tool here — it must be built
        # after cmdenv and qtenv exist, since the Makefile build links it
        # against ALL_ENV_LIBS to pull in oppcmdenv/oppqtenv at runtime.
        # See _build_opp_run_tasks().
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
            yacc = _split(cfg.yacc) if cfg and cfg.yacc else ["bison"]
            tasks.append(YaccTask(
                working_dir=src_dir,
                yacc=yacc,
                flags=list(spec.get("flags", [])),
                input_file=spec["input"],
                output_files=list(spec["outputs"]),
                name=f"{name}: {os.path.basename(spec['input'])}",
            ))
        elif kind == "lex":
            lex = _split(cfg.lex) if cfg and cfg.lex else ["flex"]
            tasks.append(LexTask(
                working_dir=src_dir,
                lex=lex,
                flags=list(spec.get("flags", [])),
                input_file=spec["input"],
                output_files=list(spec["outputs"]),
                name=f"{name}: {os.path.basename(spec['input'])}",
            ))
        elif kind == "perl":
            perl = _split(cfg.perl) if cfg and cfg.perl else ["perl"]
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
    moc = _split(cfg.moc) if cfg and cfg.moc else ["moc"]
    uic = _split(cfg.uic) if cfg and cfg.uic else ["uic"]
    rcc = _split(cfg.rcc) if cfg and cfg.rcc else ["rcc"]

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

# Source files present in the OMNeT++ tree but deliberately excluded from the
# upstream Makefile's OBJS list — mirror that exclusion here so globbing matches
# what `make` actually builds. Keyed by (component, subdir, basename); subdir is
# "" for files directly under src/<component>/.
_EXCLUDED_CC_FILES = {
    # Orphan in src/sim/parsim/: not in OBJS_PARSIM in src/sim/Makefile, and
    # doesn't compile (uses removed GateIterator::operator(); references
    # cDatarateChannel without including its header).
    ("sim", "parsim", "cadvlinkdelaylookahead.cc"),
    # rwlock.cc is added to OBJS only under `ifeq ("$(BUILDING_UILIBS)","yes")` in
    # src/common/Makefile — the task engine never builds uilibs, so skip it.
    ("common", "", "rwlock.cc"),
    # Not referenced by any Makefile's OBJS list — globbing picks them up but the
    # makefile build silently ignores them. Skip so the engines agree.
    ("eventlog", "", "ichunk.cc"),
    ("layout", "", "concentrictreeembedding.cc"),
}


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
    that aren't on the canonical generator output list), and files in
    ``_EXCLUDED_CC_FILES`` that the upstream Makefile excludes from OBJS.
    """
    base = os.path.join(omnetpp_root, "src", component)
    expected = set(expected_generated)
    files = []
    for f in sorted(glob.glob(os.path.join(base, "*.cc"))):
        basename = os.path.basename(f)
        if _is_stale_generated_cc(basename, expected):
            continue
        if (component, "", basename) in _EXCLUDED_CC_FILES:
            continue
        files.append(f)
    for sub in extra_subdirs:
        for f in sorted(glob.glob(os.path.join(base, sub, "*.cc"))):
            basename = os.path.basename(f)
            if _is_stale_generated_cc(basename, expected):
                continue
            if (component, sub, basename) in _EXCLUDED_CC_FILES:
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
            name=f"{name} build",
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

    compile_tasks = []
    for cc in cc_files:
        compile_tasks.append(OmnetppProjectCppCompileTask(
            omnetpp_project=omnetpp_project,
            component=name,
            source_file=cc,
            mode=mode,
            makefile_inc_config=cfg,
        ))
    for c in c_files:
        compile_tasks.append(OmnetppProjectCppCompileTask(
            omnetpp_project=omnetpp_project,
            component=name,
            source_file=c,
            mode=mode,
            makefile_inc_config=cfg,
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
                library_type=extra_lib.get("link_type", "shared"),
                mode=mode,
                makefile_inc_config=cfg,
                compile_tasks=extra_compile_tasks,
            ))

    # Tool executables
    for tool in component.get("tools", []):
        tool_src_rel = os.path.relpath(os.path.join(omnetpp_root, "src", name, tool["source"]), omnetpp_root)
        tool_src_abs = os.path.join(omnetpp_root, "src", name, tool["source"])
        tool_compile_task = OmnetppProjectCppCompileTask(
            omnetpp_project=omnetpp_project,
            component=name,
            source_file=tool_src_rel,
            mode=mode,
            makefile_inc_config=cfg,
        )
        debug_suffix = cfg.debug_suffix if cfg else ""
        tool_link_libs = [f"-l{library_name}{debug_suffix}"] if library_name else []
        if tool.get("link_with"):
            tool_link_libs.insert(0, f"-l{tool['link_with']}{debug_suffix}")
        tool_link_task = OmnetppProjectLinkTask(
            omnetpp_project=omnetpp_project,
            component=name,
            library_name=tool["basename"],
            is_executable=True,
            mode=mode,
            makefile_inc_config=cfg,
            compile_tasks=[tool_compile_task],
            extra_libraries=tool_link_libs + extra_libraries,
        )
        # Group compile+link under one wrapper that short-circuits when the
        # installed binary already exists (makefile build uses combined
        # compile+link, so no standalone .o is left on disk).
        tool_chain = [tool_compile_task, tool_link_task]
        # Release-only alias (e.g. bin/opp_run -> bin/opp_run_release), to
        # mirror the envir Makefile's TARGET_EXE_FILES rule for MODE=release.
        release_alias = tool.get("release_alias")
        if release_alias and mode == "release":
            exe_ext = cfg.exe_suffix if cfg else ""
            bin_dir = (cfg.omnetpp_bin_dir if cfg and cfg.omnetpp_bin_dir
                       else os.path.join(omnetpp_root, "bin"))
            source_rel = os.path.relpath(tool_link_task.output_file, omnetpp_root)
            target_rel = os.path.relpath(os.path.join(bin_dir, release_alias + exe_ext), omnetpp_root)
            tool_chain.append(OmnetppProjectCopyBinaryTask(
                omnetpp_project=omnetpp_project,
                source_file=source_rel,
                target_file=target_rel,
                name=f"{name}: install {release_alias}",
            ))
        component_tasks.append(_ToolBuildTasks(
            tasks=tool_chain,
            name=f"{tool['basename']} build",
            concurrent=False,
            executable_path=tool_link_task.output_file,
            source_file=tool_src_abs,
        ))

    if not component_tasks:
        return None
    return _RecursiveBuildTasks(
        tasks=component_tasks,
        name=f"{name} build",
        concurrent=False,  # within a component, ordering matters (compile -> link)
    )


def _build_opp_run_tasks(omnetpp_project, mode, cfg, concurrent):
    """
    Build the ``opp_run`` executable (and ``opp_run_release`` in release mode).

    Runs after all per-component tasks, since the Makefile build links
    ``opp_run`` against ``ALL_ENV_LIBS`` (oppcmdenv + oppqtenv) to force
    the user interface libraries to be loaded at runtime via
    ``-Wl,--no-as-needed``. Without these libs in the link line, the binary
    starts up with "No user interface (Cmdenv, Qtenv, etc.) found".
    """
    omnetpp_root = omnetpp_project.get_root_path()
    debug_suffix = cfg.debug_suffix if cfg else ""

    main_src_rel = os.path.relpath(
        os.path.join(omnetpp_root, "src", "envir", "main.cc"), omnetpp_root)
    compile_task = OmnetppProjectCppCompileTask(
        omnetpp_project=omnetpp_project,
        component="envir",
        source_file=main_src_rel,
        mode=mode,
        makefile_inc_config=cfg,
    )

    # Link line mirrors src/envir/Makefile: $(ALL_ENV_LIBS) $(IMPLIBS) $(SYS_LIBS)
    # ALL_ENV_LIBS already contains -loppcmdenv, -loppqtenv, the -Wl,--no-as-needed
    # markers, and the QT/OSG libs as the configure step decided.
    all_env_libs = _split(cfg.all_env_libs) if cfg else [
        f"-loppcmdenv{debug_suffix}", f"-loppenvir{debug_suffix}"]
    implibs = [f"-loppsim{debug_suffix}",
               f"-loppnedxml{debug_suffix}",
               f"-loppcommon{debug_suffix}"]
    extra_libraries = [*all_env_libs, *implibs]

    link_task = OmnetppProjectLinkTask(
        omnetpp_project=omnetpp_project,
        component="envir",
        library_name="opp_run",
        is_executable=True,
        mode=mode,
        makefile_inc_config=cfg,
        compile_tasks=[compile_task],
        extra_libraries=extra_libraries,
    )

    tasks = [compile_task, link_task]

    if mode == "release":
        exe_ext = cfg.exe_suffix if cfg else ""
        bin_dir = (cfg.omnetpp_bin_dir if cfg and cfg.omnetpp_bin_dir
                   else os.path.join(omnetpp_root, "bin"))
        source_rel = os.path.relpath(link_task.output_file, omnetpp_root)
        target_rel = os.path.relpath(os.path.join(bin_dir, "opp_run_release" + exe_ext), omnetpp_root)
        tasks.append(OmnetppProjectCopyBinaryTask(
            omnetpp_project=omnetpp_project,
            source_file=source_rel,
            target_file=target_rel,
            name="envir: install opp_run_release",
        ))

    return _RecursiveBuildTasks(
        tasks=tasks,
        name="opp_run build",
        concurrent=False,  # compile -> link -> copy
    )


class ConfigureOmnetppTask(Task):
    """
    Runs ``./configure`` in the OMNeT++ root directory if ``Makefile.inc``
    does not yet exist. If ``configure.user`` is also missing, it is copied
    from the original source tree (falling back to ``configure.user.dist``).
    """

    def __init__(self, omnetpp_project=None, name="configure OMNeT++", action="Configuring", **kwargs):
        super().__init__(name=name, action=action, **kwargs)
        self.omnetpp_project = omnetpp_project

    def get_parameters_string(self, **kwargs):
        return self.omnetpp_project.get_root_path() if self.omnetpp_project.has_root_path() else ""

    def is_up_to_date(self):
        if not self.omnetpp_project.has_root_path():
            return True
        return os.path.isfile(os.path.join(self.omnetpp_project.get_root_path(), "Makefile.inc"))

    def run_protected(self, **kwargs):
        import shutil
        from opp_repl.simulation.project import _get_git_root
        root = self.omnetpp_project.get_root_path()
        configure_user = os.path.join(root, "configure.user")
        if not os.path.isfile(configure_user):
            git_root = _get_git_root(root)
            source_configure_user = os.path.join(git_root, "configure.user")
            if os.path.isfile(source_configure_user):
                shutil.copy2(source_configure_user, configure_user)
            else:
                dist = os.path.join(root, "configure.user.dist")
                if os.path.isfile(dist):
                    shutil.copy2(dist, configure_user)
        _logger.info("Running ./configure in %s", root)
        env = os.environ.copy()
        env["__omnetpp_root_dir"] = root
        env["PATH"] = os.path.join(root, "bin") + os.pathsep + env.get("PATH", "")
        env["PYTHONPATH"] = os.path.join(root, "python") + os.pathsep + env.get("PYTHONPATH", "")
        run_command_with_logging(["./configure"], cwd=root, env=env, error_message="Configuring OMNeT++ failed")
        return self.task_result_class(task=self, result="DONE")


def build_omnetpp(build_engine=None, **kwargs):
    """
    Builds OMNeT++ using either :py:func:`build_omnetpp_using_makefile` or
    :py:func:`build_omnetpp_using_tasks`.

    Parameters:
        build_engine (str):
            Specifies the requested build engine. Valid values are
            ``"makefile"`` and ``"task"``. If unspecified, the global default
            from :py:func:`get_default_build_engine` is used.

        kwargs (dict):
            Additional parameters are forwarded to the selected builder.
    """
    if build_engine is None:
        from opp_repl.simulation.build import get_default_build_engine
        build_engine = get_default_build_engine()
    if build_engine == "makefile":
        build_function = build_omnetpp_using_makefile
    elif build_engine == "task":
        build_function = build_omnetpp_using_tasks
    else:
        raise Exception(f"Unknown build_engine argument: {build_engine}")
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
    static_ext = (getattr(cfg, "a_lib_suffix", ".a") if cfg else ".a") or ".a"
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

    # Extra libraries (e.g. oppmain — static archive)
    for extra_lib in component.get("extra_libraries", []):
        ext = static_ext if extra_lib.get("link_type") == "static" else shared_ext
        lib_file = os.path.join(lib_dir, lib_prefix + extra_lib["basename"] + debug_suffix + ext)
        tasks.append(_CleanFileTask(working_dir=omnetpp_root, file_path=lib_file))

    # Tool executables (opp_nedtool, opp_msgtool, opp_run, ...)
    for tool in component.get("tools", []):
        exe_file = os.path.join(bin_dir, tool["basename"] + debug_suffix + exe_ext)
        tasks.append(_CleanFileTask(working_dir=omnetpp_root, file_path=exe_file))
        release_alias = tool.get("release_alias")
        if release_alias and mode == "release":
            alias_file = os.path.join(bin_dir, release_alias + exe_ext)
            tasks.append(_CleanFileTask(working_dir=omnetpp_root, file_path=alias_file))

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


def clean_omnetpp(build_engine=None, **kwargs):
    """
    Cleans OMNeT++ using either :py:func:`clean_omnetpp_using_makefile` or
    :py:func:`clean_omnetpp_using_tasks`.

    Parameters:
        build_engine (str):
            ``"makefile"`` runs ``make clean`` in the OMNeT++ tree.
            ``"task"`` removes generated sources, built objects, libraries and
            executables directly. If unspecified, the global default from
            :py:func:`get_default_build_engine` is used.
    """
    if build_engine is None:
        from opp_repl.simulation.build import get_default_build_engine
        build_engine = get_default_build_engine()
    if build_engine == "makefile":
        clean_function = clean_omnetpp_using_makefile
    elif build_engine == "task":
        clean_function = clean_omnetpp_using_tasks
    else:
        raise Exception(f"Unknown build_engine argument: {build_engine}")
    return clean_function(**kwargs)


def clean_omnetpp_using_makefile(omnetpp_project=None, mode="release", **kwargs):
    """Run ``make clean`` in the OMNeT++ root for the given mode."""
    if omnetpp_project is None:
        raise RuntimeError("omnetpp_project is required")
    omnetpp_project.ensure_mounted()
    root = omnetpp_project.get_root_path()
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
                name=f"{component['name']} clean",
                concurrent=concurrent,
            ))

    # opp_run / opp_run_release are built in a post-pass (see
    # _build_opp_run_tasks), so they're not covered by any per-component clean.
    debug_suffix = cfg.debug_suffix if cfg else ""
    exe_ext = cfg.exe_suffix if cfg else ""
    bin_dir = (cfg.omnetpp_bin_dir if cfg and cfg.omnetpp_bin_dir
               else os.path.join(omnetpp_root, "bin"))
    opp_run_clean_tasks = [
        _CleanFileTask(
            working_dir=omnetpp_root,
            file_path=os.path.join(bin_dir, "opp_run" + debug_suffix + exe_ext),
        ),
    ]
    if mode == "release":
        opp_run_clean_tasks.append(_CleanFileTask(
            working_dir=omnetpp_root,
            file_path=os.path.join(bin_dir, "opp_run_release" + exe_ext),
        ))
    component_tasks.append(_MultipleCleanTasks(
        tasks=opp_run_clean_tasks,
        name="opp_run clean",
        concurrent=concurrent,
    ))

    # Output directory (out/<configname>/, or all of out/ if no config)
    out_path = f"out/{cfg.configname}" if cfg else "out"
    component_tasks.append(_CleanDirectoryTask(
        working_dir=omnetpp_root, directory_path=out_path,
        name="output directory clean",
    ))

    top_task = _MultipleCleanTasks(
        tasks=component_tasks,
        name=f"OMNeT++ ({mode}) clean",
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

    # opp_run must be linked after cmdenv/qtenv are built — see _build_opp_run_tasks().
    opp_run_task = _build_opp_run_tasks(omnetpp_project, mode, makefile_inc_config, concurrent)
    if opp_run_task is not None:
        component_tasks.append(opp_run_task)

    top_task = _RecursiveBuildTasks(
        tasks=component_tasks,
        name=f"OMNeT++ ({mode}) build",
        concurrent=False,  # components must be built in dependency order
    )
    top_task.log_structure()
    return top_task.run(**kwargs)
