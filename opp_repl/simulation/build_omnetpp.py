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
import os
import re
import shlex

from opp_repl.common.compile import *
from opp_repl.common.task import *

_logger = logging.getLogger(__name__)


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
        include_dirs = [
            cfg.omnetpp_incl_dir if cfg else os.path.join(omnetpp_root, "include"),
            cfg.omnetpp_src_dir if (cfg and cfg.omnetpp_src_dir) else os.path.join(omnetpp_root, "src"),
        ]

        output_folder = _omnetpp_output_folder(cfg, component, mode)
        ext = ".c" if is_c else ".cc"
        obj_name = re.sub(rf"\{ext}$", ".o", os.path.basename(source_file))
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
            libraries = [*[f"-l{lib}" for lib in (extra_libraries or [])], *sys_libs]
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
            libraries = [*[f"-l{lib}" for lib in (extra_libraries or [])], *sys_libs]
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
#   utility_scripts:  for the "utils" component, list of files to copy to bin/
#   conditional_var:  None or makefile_inc_config attr name (e.g. "with_qtenv")
#                     to gate the whole component
#   c_files:          .c (not .cc) files to compile
#
# Tool executables (e.g. opp_nedtool from nedxml) are linked from a single
# .cc file plus the component's library — that mapping is in `tools` below.
OMNETPP_COMPONENTS = [
    {
        "name": "utils",
        "library_name": None,
        "define": None,
        "subdirs": [],
        "excludes": [],
        "utility_scripts": [],  # populated dynamically by globbing src/utils
        "c_files": [],
    },
    {
        "name": "common",
        "library_name": "oppcommon",
        "define": "COMMON_EXPORT",
        "subdirs": [],
        "excludes": [],
        "c_files": ["sqlite3.c", "yxml.c"],
    },
    {
        "name": "nedxml",
        "library_name": "oppnedxml",
        "define": "NEDXML_EXPORT",
        "subdirs": [],
        "excludes": ["opp_nedtool.cc", "opp_msgtool.cc"],
        "c_files": [],
        "tools": [
            {"basename": "opp_nedtool", "source": "opp_nedtool.cc"},
            {"basename": "opp_msgtool", "source": "opp_msgtool.cc"},
        ],
    },
    {
        "name": "layout",
        "library_name": "opplayout",
        "define": "LAYOUT_EXPORT",
        "subdirs": [],
        "excludes": [],
        "c_files": [],
    },
    {
        "name": "eventlog",
        "library_name": "oppeventlog",
        "define": "EVENTLOG_EXPORT",
        "subdirs": [],
        "excludes": ["opp_eventlogtool.cc"],
        "c_files": [],
        "tools": [
            {"basename": "opp_eventlogtool", "source": "opp_eventlogtool.cc"},
        ],
    },
    {
        "name": "scave",
        "library_name": "oppscave",
        "define": "SCAVE_EXPORT",
        "subdirs": [],
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
        "subdirs": [],  # netbuilder, parsim added conditionally
        "excludes": [],
        "c_files": [],
    },
    {
        "name": "envir",
        "library_name": "oppenvir",
        "define": "ENVIR_EXPORT",
        "subdirs": [],
        "excludes": ["main.cc"],
        "c_files": [],
        "extra_libraries": [
            {"basename": "oppmain", "source_files": ["main.cc"]},
        ],
        "tools": [
            {"basename": "opp_run", "source": "main.cc", "link_with": "oppmain"},
        ],
    },
    {
        "name": "cmdenv",
        "library_name": "oppcmdenv",
        "define": "CMDENV_EXPORT",
        "subdirs": [],
        "excludes": [],
        "c_files": [],
    },
    {
        "name": "qtenv",
        "library_name": "oppqtenv",
        "define": "QTENV_EXPORT",
        "subdirs": [],
        "excludes": [],
        "c_files": [],
        "conditional_var": "with_qtenv",
    },
]


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def _glob_component_cc_files(omnetpp_root, component, extra_subdirs=()):
    """Return all *.cc files relative to omnetpp_root for a given component."""
    base = os.path.join(omnetpp_root, "src", component)
    files = sorted(glob.glob(os.path.join(base, "*.cc")))
    for sub in extra_subdirs:
        files += sorted(glob.glob(os.path.join(base, sub, "*.cc")))
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
    """Per-component extra compile flags from features (Qt, MPI, Python, ...)."""
    cfg = makefile_inc_config
    if not cfg:
        return []
    name = component["name"]
    flags = []
    if name == "common":
        flags += _split(cfg.libxml_cflags)
        if cfg.with_backtrace:
            flags.append("-DWITH_BACKTRACE")
    if name == "sim":
        if cfg.with_python:
            flags += _split(cfg.python_embed_cflags)
        flags += _split(cfg.akaroa_cflags)
    if name == "qtenv":
        flags += _split(cfg.qt_cflags)
    if name == "envir" and cfg.with_parsim:
        flags += _split(cfg.mpi_cflags)
    return flags


def _component_extra_libraries(component, makefile_inc_config):
    """Per-component extra link libraries (returned as bare names for -l)."""
    cfg = makefile_inc_config
    if not cfg:
        return []
    name = component["name"]
    libs = []
    if name == "common":
        libs += [_strip_lflag(x) for x in _split(cfg.libxml_libs)]
        if cfg.with_backtrace:
            libs += [_strip_lflag(x) for x in _split(cfg.backward_ldflags)]
    if name == "sim" and cfg.with_python:
        libs += [_strip_lflag(x) for x in _split(cfg.python_embed_ldflags)]
    if name == "qtenv":
        libs += [_strip_lflag(x) for x in _split(cfg.qt_libs)]
    if name == "envir" and cfg.with_parsim:
        libs += [_strip_lflag(x) for x in _split(cfg.mpi_libs)]
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
        return MultipleTasks(
            tasks=copy_tasks,
            name=f"build {name}",
            concurrent=concurrent,
            multiple_task_results_class=MultipleBuildTaskResults,
        )

    # Compile tasks
    excludes = set(component.get("excludes", []))
    # Also exclude sources reserved for tools/extra libraries
    for tool in component.get("tools", []):
        excludes.add(tool["source"])
    for lib in component.get("extra_libraries", []):
        for src in lib.get("source_files", []):
            excludes.add(src)

    cc_files = _glob_component_cc_files(omnetpp_root, name,
                                        extra_subdirs=_component_extra_subdirs(component, cfg))
    cc_files = [f for f in cc_files if os.path.basename(f) not in excludes]
    c_files = _glob_component_c_files(omnetpp_root, name, component.get("c_files", []))

    extra_cflags = _component_extra_cflags(component, cfg)
    extra_defines = []
    if component.get("define"):
        extra_defines.append(f"-D{component['define']}")

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

    if compile_tasks:
        component_tasks.append(MultipleTasks(
            tasks=compile_tasks,
            name=f"compile {name}",
            concurrent=concurrent,
            multiple_task_results_class=MultipleBuildTaskResults,
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
            component_tasks.append(MultipleTasks(
                tasks=extra_compile_tasks,
                name=f"compile {extra_lib['basename']}",
                concurrent=concurrent,
                multiple_task_results_class=MultipleBuildTaskResults,
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
        tool_link_libs = [library_name] if library_name else []
        if tool.get("link_with"):
            tool_link_libs.insert(0, tool["link_with"])
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
    return MultipleTasks(
        tasks=component_tasks,
        name=f"build {name}",
        concurrent=False,  # within a component, ordering matters (compile -> link)
        multiple_task_results_class=MultipleBuildTaskResults,
    )


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

    top_task = MultipleTasks(
        tasks=component_tasks,
        name=f"build OMNeT++ ({mode})",
        concurrent=False,  # components must be built in dependency order
        multiple_task_results_class=MultipleBuildTaskResults,
    )
    top_task.log_structure()
    return top_task.run(**kwargs)
