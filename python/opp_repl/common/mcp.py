"""
This module provides an MCP (Model Context Protocol) server for the INET Framework Python library.

The server runs on a background thread and exposes tools for running simulations, comparing simulations,
running fingerprint tests, and running statistical tests. It allows AI assistants to connect and interact
with the INET simulation framework.
"""

import builtins
import logging
import threading
from collections import namedtuple

from mcp.server.fastmcp import FastMCP

from opp_repl.common.util import *
from opp_repl.project.omnetpp import *
from opp_repl.simulation.compare import *
from opp_repl.simulation.project import *
from opp_repl.simulation.task import *
from opp_repl.test.fingerprint.task import *
from opp_repl.test.statistical import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

_mcp = FastMCP("inet", host="127.0.0.1", port=9966, stateless_http=True)

McpCall = namedtuple("McpCall", ["tool", "kwargs", "result"])
mcp_calls = []

def _strip_ansi(text):
    import re
    return re.sub(r"\033\[[0-9;]*m", "", str(text))

def _format_result(result):
    return _strip_ansi(builtins.repr(result))

def _log_mcp_call(tool_name, kwargs):
    args_str = ", ".join(f"{k}={v!r}" for k, v in kwargs.items() if v is not None)
    _logger.info(f"{tool_name}({args_str})")

def _log_mcp_result(tool_name, kwargs, result):
    mcp_calls.append(McpCall(tool_name, kwargs, result))
    result_repr = _strip_ansi(builtins.repr(result))
    if len(result_repr) > 200:
        result_repr = result_repr[:200] + "..."
    _logger.info(f"{tool_name} \u2192 {result_repr}")

@_mcp.tool()
def list_simulation_projects() -> str:
    """List all defined simulation projects.

    Returns the names and versions of all simulation projects that have been
    defined (registered) in the current Python session, along with their
    root folder and whether each one is currently the default project.

    Returns:
        A text listing of all defined simulation projects.
    """
    _log_mcp_call("list_simulation_projects", {})
    from opp_repl.simulation.project import simulation_projects, get_default_simulation_project
    try:
        default = get_default_simulation_project()
    except Exception:
        default = None
    lines = []
    for (name, version), project in simulation_projects.items():
        is_default = " [default]" if project is default else ""
        ver_str = f" version={version}" if version is not None else ""
        folder = project.get_full_path(".")
        lines.append(f"{name}{ver_str} folder={folder}{is_default}")
    if not lines:
        text = "No simulation projects are defined."
    else:
        text = f"{len(lines)} simulation project(s) defined:\n" + "\n".join(lines)
    _log_mcp_result("list_simulation_projects", {}, text)
    return text

@_mcp.tool()
def define_simulation_project(name: str,
                   version: str = None,
                   folder_environment_variable: str = None,
                   folder: str = ".",
                   omnetpp_environment_variable: str = "__omnetpp_root_dir",
                   bin_folder: str = ".",
                   library_folder: str = ".",
                   executables: str = None,
                   dynamic_libraries: str = None,
                   static_libraries: str = None,
                   ned_folders: str = ".",
                   ned_exclusions: str = None,
                   ini_file_folders: str = ".",
                   image_folders: str = ".",
                   include_folders: str = ".",
                   cpp_folders: str = ".",
                   msg_folders: str = ".",
                   statistics_folder: str = ".",
                   fingerprint_store: str = "fingerprint.json",
                   speed_store: str = "speed.json",
                   set_as_default: bool = True) -> str:
    """Define (register) a new simulation project.

    List parameters (ned_folders, ini_file_folders, etc.) accept
    comma-separated values, e.g. "src,examples,showcases".

    Args:
        name: The name of the simulation project.
        version: Optional version string.
        folder_environment_variable: OS environment variable pointing to the project root.
        folder: Project directory relative to folder_environment_variable (default ".").
        omnetpp_environment_variable: OS env var for the OMNeT++ root dir.
        bin_folder: Directory for binary outputs (relative to project root).
        library_folder: Directory for library outputs (relative to project root).
        executables: Comma-separated list of executable names to build.
        dynamic_libraries: Comma-separated list of dynamic library names to build.
        static_libraries: Comma-separated list of static library names to build.
        ned_folders: Comma-separated list of NED source directories.
        ned_exclusions: Comma-separated list of excluded NED packages.
        ini_file_folders: Comma-separated list of directories containing INI files.
        image_folders: Comma-separated list of image directories.
        include_folders: Comma-separated list of C++ include directories.
        cpp_folders: Comma-separated list of C++ source directories.
        msg_folders: Comma-separated list of MSG source directories.
        statistics_folder: Directory for scalar statistics result files.
        fingerprint_store: Relative path to the JSON fingerprint store.
        speed_store: Relative path to the JSON speed measurement store.
        set_as_default: If True, set this project as the default (default True).

    Returns:
        A confirmation message with the project's root folder.
    """
    def _split(s):
        return [x.strip() for x in s.split(",") if x.strip()] if s else []

    _log_mcp_call("define_simulation_project", {"name": name, "version": version})
    from opp_repl.simulation.project import define_simulation_project as _define_simulation_project, set_default_simulation_project as _set_default_simulation_project
    kwargs = dict(
        folder_environment_variable=folder_environment_variable,
        folder=folder,
        omnetpp_environment_variable=omnetpp_environment_variable,
        bin_folder=bin_folder,
        library_folder=library_folder,
        ned_folders=_split(ned_folders),
        ini_file_folders=_split(ini_file_folders),
        image_folders=_split(image_folders),
        include_folders=_split(include_folders),
        cpp_folders=_split(cpp_folders),
        msg_folders=_split(msg_folders),
        statistics_folder=statistics_folder,
        fingerprint_store=fingerprint_store,
        speed_store=speed_store,
    )
    if executables is not None:
        kwargs["executables"] = _split(executables)
    if dynamic_libraries is not None:
        kwargs["dynamic_libraries"] = _split(dynamic_libraries)
    if static_libraries is not None:
        kwargs["static_libraries"] = _split(static_libraries)
    if ned_exclusions is not None:
        kwargs["ned_exclusions"] = _split(ned_exclusions)
    project = _define_simulation_project(name, version=version, **kwargs)
    if set_as_default:
        _set_default_simulation_project(project)
    root = project.get_full_path(".")
    ver_str = f" version={version}" if version is not None else ""
    default_str = " (set as default)" if set_as_default else ""
    text = f"Simulation project '{name}'{ver_str} defined, root folder: {root}{default_str}"
    _log_mcp_result("define_simulation_project", {"name": name, "version": version}, project)
    return text

@_mcp.tool()
def set_default_simulation_project(name: str, version: str = None) -> str:
    """Set the default simulation project by name (and optionally version).

    Args:
        name: The name of the simulation project to set as default.
        version: The version of the simulation project (optional).

    Returns:
        A confirmation message.
    """
    _log_mcp_call("set_default_simulation_project", {"name": name, "version": version})
    from opp_repl.simulation.project import get_simulation_project, set_default_simulation_project as _set_default_simulation_project
    project = get_simulation_project(name, version)
    _set_default_simulation_project(project)
    ver_str = f" version={version}" if version is not None else ""
    _log_mcp_result("set_default_simulation_project", {"name": name, "version": version}, project)
    return f"Default simulation project set to: {name}{ver_str}"

@_mcp.tool()
def build_simulation_project(name: str = None,
                             version: str = None,
                             mode: str = "release",
                             build_mode: str = "makefile") -> str:
    """Build a simulation project.

    Builds the specified simulation project (or the default one if not given)
    using either the Makefile or task-based build system.

    Args:
        name: Name of the simulation project to build. Uses the default project if not specified.
        version: Version of the simulation project (optional).
        mode: Build mode: "release" (default), "debug", "sanitize", "coverage", or "profile".
        build_mode: Build system to use: "makefile" (default) or "task".

    Returns:
        A confirmation message on success.
    """
    _log_mcp_call("build_simulation_project", {"name": name, "mode": mode, "build_mode": build_mode})
    from opp_repl.simulation.project import get_simulation_project, get_default_simulation_project
    from opp_repl.simulation.build import build_project as _build_project
    if name is not None:
        project = get_simulation_project(name, version)
    else:
        project = get_default_simulation_project()
    _build_project(simulation_project=project, mode=mode, build_mode=build_mode)
    text = f"Build of '{project.get_name()}' in {mode} mode completed successfully."
    _log_mcp_result("build_simulation_project", {"name": name, "mode": mode, "build_mode": build_mode}, text)
    return text

@_mcp.tool()
def get_simulation_configs(working_directory_filter: str = None,
                           ini_file_filter: str = None,
                           config_filter: str = None,
                           filter: str = None,
                           exclude_filter: str = None) -> str:
    """List simulation configs matching the provided filter criteria.

    Returns the list of available simulation configurations from the default
    simulation project (usually INET). Each config has a working directory,
    INI file, config name, number of runs, and optional sim time limit.

    Args:
        working_directory_filter: include configs from a specific working directory (regex)
        ini_file_filter: include configs from matching INI files (regex)
        config_filter: include configs having matching config sections (regex)
        filter: generic filter that matches any part of the config description
        exclude_filter: exclude configs matching this generic filter

    Returns:
        A text listing of matching simulation configs with their properties.
    """
    kwargs = {}
    if working_directory_filter is not None:
        kwargs["working_directory_filter"] = working_directory_filter
    if ini_file_filter is not None:
        kwargs["ini_file_filter"] = ini_file_filter
    if config_filter is not None:
        kwargs["config_filter"] = config_filter
    if filter is not None:
        kwargs["filter"] = filter
    if exclude_filter is not None:
        kwargs["exclude_filter"] = exclude_filter
    _log_mcp_call("get_simulation_configs", kwargs)
    from opp_repl.simulation.project import get_default_simulation_project
    simulation_project = get_default_simulation_project()
    simulation_configs = simulation_project.get_simulation_configs(**kwargs)
    _log_mcp_result("get_simulation_configs", kwargs, simulation_configs)
    lines = []
    for sc in simulation_configs:
        parts = [sc.working_directory]
        if sc.ini_file != "omnetpp.ini":
            parts.append(f"-f {sc.ini_file}")
        if sc.config != "General":
            parts.append(f"-c {sc.config}")
        parts.append(f"({sc.num_runs} run{'s' if sc.num_runs != 1 else ''})")
        if sc.sim_time_limit:
            parts.append(f"limit={sc.sim_time_limit}")
        lines.append(" ".join(parts))
    return f"{len(simulation_configs)} simulation configs found:\n" + "\n".join(lines)

@_mcp.tool()
def run_simulations(working_directory_filter: str = None,
                    ini_file_filter: str = None,
                    config_filter: str = None,
                    run_number_filter: str = None,
                    run_number: int = None,
                    sim_time_limit: str = None,
                    cpu_time_limit: str = None,
                    filter: str = None,
                    exclude_filter: str = None,
                    mode: str = "release",
                    build: bool = True,
                    concurrent: bool = True) -> str:
    """Run one or more INET simulations matching the provided filter criteria.

    Simulations are collected from the default simulation project (usually INET)
    based on working directory, INI file, config section, and run number filters.
    They can be run sequentially or concurrently.

    Args:
        working_directory_filter: include simulations from a specific working directory (regex)
        ini_file_filter: include simulations from matching INI files (regex)
        config_filter: include simulations having matching config sections (regex)
        run_number_filter: include simulations having matching run numbers (regex)
        run_number: run only this specific run number
        sim_time_limit: simulation time limit as quantity with unit (e.g. "1s", "10ms")
        cpu_time_limit: CPU time limit as quantity with unit (e.g. "60s")
        filter: generic filter that matches any part of the simulation description
        exclude_filter: exclude simulations matching this generic filter
        mode: build mode, "release" or "debug"
        build: whether to build the project before running
        concurrent: whether to run simulations concurrently

    Returns:
        A text summary of the simulation results including per-simulation status
        (DONE, ERROR, CANCEL, SKIP) and an overall summary.
    """
    kwargs = {}
    if working_directory_filter is not None:
        kwargs["working_directory_filter"] = working_directory_filter
    if ini_file_filter is not None:
        kwargs["ini_file_filter"] = ini_file_filter
    if config_filter is not None:
        kwargs["config_filter"] = config_filter
    if run_number_filter is not None:
        kwargs["run_number_filter"] = run_number_filter
    if run_number is not None:
        kwargs["run_number"] = run_number
    if sim_time_limit is not None:
        kwargs["sim_time_limit"] = sim_time_limit
    if cpu_time_limit is not None:
        kwargs["cpu_time_limit"] = cpu_time_limit
    if filter is not None:
        kwargs["filter"] = filter
    if exclude_filter is not None:
        kwargs["exclude_filter"] = exclude_filter
    kwargs["mode"] = mode
    kwargs["build"] = build
    kwargs["concurrent"] = concurrent
    _log_mcp_call("run_simulations", kwargs)
    from opp_repl.simulation.task import run_simulations as _run_simulations
    result = _run_simulations(**kwargs)
    _log_mcp_result("run_simulations", kwargs, result)
    return _format_result(result)

@_mcp.tool()
def compare_simulations(working_directory_filter: str = None,
                        ini_file_filter: str = None,
                        config_filter: str = None,
                        run_number: int = 0,
                        sim_time_limit: str = None,
                        project_1: str = None,
                        project_2: str = None,
                        mode_1: str = "release",
                        mode_2: str = "release",
                        build: bool = True,
                        concurrent: bool = True) -> str:
    """Compare two simulation runs to find divergences in stdout, fingerprint trajectories, and statistical results.

    This tool runs the same simulation twice (potentially with different modes or
    parameters) and compares the results. It detects divergences in:
    - stdout trajectory (logged output)
    - fingerprint trajectory (simulation execution path)
    - statistical results (scalar output values)

    Use the _1 and _2 suffixed parameters to differentiate between the two runs.

    Args:
        working_directory_filter: include simulations from a specific working directory (regex)
        ini_file_filter: include simulations from matching INI files (regex)
        config_filter: include simulations having matching config sections (regex)
        run_number: the run number to compare (default 0)
        sim_time_limit: simulation time limit as quantity with unit (e.g. "1s")
        project_1: designator for the first simulation project — registered name (e.g. "inet"),
                   name:version (e.g. "inet:4.5"), or folder path (e.g. "../inet-baseline").
                   Defaults to the default project.
        project_2: designator for the second simulation project (same syntax as project_1).
                   Defaults to the default project.
        mode_1: build mode for first simulation ("release" or "debug")
        mode_2: build mode for second simulation ("release" or "debug")
        build: whether to build the project before running
        concurrent: whether to run simulations concurrently

    Returns:
        A text summary showing comparison results: IDENTICAL, DIVERGENT, or DIFFERENT,
        with details about stdout, fingerprint, and statistical differences.
    """
    kwargs = {}
    if working_directory_filter is not None:
        kwargs["working_directory_filter"] = working_directory_filter
    if ini_file_filter is not None:
        kwargs["ini_file_filter"] = ini_file_filter
    if config_filter is not None:
        kwargs["config_filter"] = config_filter
    if run_number is not None:
        kwargs["run_number"] = run_number
    if sim_time_limit is not None:
        kwargs["sim_time_limit"] = sim_time_limit
    from opp_repl.simulation.project import resolve_simulation_project
    if project_1 is not None:
        kwargs["simulation_project_1"] = resolve_simulation_project(project_1)
    if project_2 is not None:
        kwargs["simulation_project_2"] = resolve_simulation_project(project_2)
    kwargs["mode_1"] = mode_1
    kwargs["mode_2"] = mode_2
    kwargs["build"] = build
    kwargs["concurrent"] = concurrent
    _log_mcp_call("compare_simulations", kwargs)
    from opp_repl.simulation.compare import compare_simulations as _compare_simulations
    result = _compare_simulations(**kwargs)
    _log_mcp_result("compare_simulations", kwargs, result)
    return _format_result(result)

@_mcp.tool()
def run_fingerprint_tests(working_directory_filter: str = None,
                          ini_file_filter: str = None,
                          config_filter: str = None,
                          run_number_filter: str = None,
                          run_number: int = None,
                          sim_time_limit: str = None,
                          filter: str = None,
                          exclude_filter: str = None,
                          mode: str = "release",
                          build: bool = True,
                          concurrent: bool = True) -> str:
    """Run fingerprint tests to detect regressions in the simulation execution trajectory.

    Fingerprint tests compare the calculated fingerprint of a simulation run against
    a stored correct fingerprint in the database. A fingerprint captures the simulation
    trajectory (timing, packets, topology, etc.) in a compact hash. A mismatch indicates
    a regression.

    Args:
        working_directory_filter: include simulations from a specific working directory (regex)
        ini_file_filter: include simulations from matching INI files (regex)
        config_filter: include simulations having matching config sections (regex)
        run_number_filter: include simulations having matching run numbers (regex)
        run_number: run only this specific run number
        sim_time_limit: simulation time limit as quantity with unit (e.g. "1s")
        filter: generic filter that matches any part of the simulation description
        exclude_filter: exclude simulations matching this generic filter
        mode: build mode, "release" or "debug"
        build: whether to build the project before running
        concurrent: whether to run simulations concurrently

    Returns:
        A text summary of the fingerprint test results including per-test status
        (PASS, FAIL, SKIP, ERROR) and an overall summary.
    """
    kwargs = {}
    if working_directory_filter is not None:
        kwargs["working_directory_filter"] = working_directory_filter
    if ini_file_filter is not None:
        kwargs["ini_file_filter"] = ini_file_filter
    if config_filter is not None:
        kwargs["config_filter"] = config_filter
    if run_number_filter is not None:
        kwargs["run_number_filter"] = run_number_filter
    if run_number is not None:
        kwargs["run_number"] = run_number
    if sim_time_limit is not None:
        kwargs["sim_time_limit"] = sim_time_limit
    if filter is not None:
        kwargs["filter"] = filter
    if exclude_filter is not None:
        kwargs["exclude_filter"] = exclude_filter
    kwargs["mode"] = mode
    kwargs["build"] = build
    kwargs["concurrent"] = concurrent
    _log_mcp_call("run_fingerprint_tests", kwargs)
    from opp_repl.test.fingerprint.task import run_fingerprint_tests as _run_fingerprint_tests
    result = _run_fingerprint_tests(**kwargs)
    _log_mcp_result("run_fingerprint_tests", kwargs, result)
    return _format_result(result)

@_mcp.tool()
def run_statistical_tests(working_directory_filter: str = None,
                          ini_file_filter: str = None,
                          config_filter: str = None,
                          run_number_filter: str = None,
                          run_number: int = None,
                          sim_time_limit: str = None,
                          filter: str = None,
                          exclude_filter: str = None,
                          mode: str = "release",
                          build: bool = True,
                          concurrent: bool = True) -> str:
    """Run statistical tests to detect regressions in scalar simulation results.

    Statistical tests run simulations and compare the resulting scalar statistics
    (e.g. throughput, delay, packet loss) against stored baseline results. Differences
    indicate a regression in the simulation behavior.

    The baseline results are stored in the statistics folder of the simulation project.

    Args:
        working_directory_filter: include simulations from a specific working directory (regex)
        ini_file_filter: include simulations from matching INI files (regex)
        config_filter: include simulations having matching config sections (regex)
        run_number_filter: include simulations having matching run numbers (regex)
        run_number: run only this specific run number
        sim_time_limit: simulation time limit as quantity with unit (e.g. "1s")
        filter: generic filter that matches any part of the simulation description
        exclude_filter: exclude simulations matching this generic filter
        mode: build mode, "release" or "debug"
        build: whether to build the project before running
        concurrent: whether to run simulations concurrently

    Returns:
        A text summary of the statistical test results including per-test status
        (PASS, FAIL, SKIP, ERROR) and an overall summary.
    """
    kwargs = {}
    if working_directory_filter is not None:
        kwargs["working_directory_filter"] = working_directory_filter
    if ini_file_filter is not None:
        kwargs["ini_file_filter"] = ini_file_filter
    if config_filter is not None:
        kwargs["config_filter"] = config_filter
    if run_number_filter is not None:
        kwargs["run_number_filter"] = run_number_filter
    if run_number is not None:
        kwargs["run_number"] = run_number
    if sim_time_limit is not None:
        kwargs["sim_time_limit"] = sim_time_limit
    if filter is not None:
        kwargs["filter"] = filter
    if exclude_filter is not None:
        kwargs["exclude_filter"] = exclude_filter
    kwargs["mode"] = mode
    kwargs["build"] = build
    kwargs["concurrent"] = concurrent
    _log_mcp_call("run_statistical_tests", kwargs)
    from opp_repl.test.statistical import run_statistical_tests as _run_statistical_tests
    result = _run_statistical_tests(**kwargs)
    _log_mcp_result("run_statistical_tests", kwargs, result)
    return _format_result(result)

def start_mcp_server(port=9966):
    """Start the MCP server on a background thread using Streamable HTTP transport.

    The server uses stateless HTTP mode so each tool call is an independent
    HTTP POST request. This makes server restarts transparent to clients —
    no persistent connection needs to be re-established.

    Endpoint: http://127.0.0.1:{port}/mcp

    Args:
        port: The port to listen on (default 9966).
    """
    _mcp.settings.port = port
    _mcp.settings.log_level = "WARNING"
    logging.getLogger("mcp").setLevel(logging.WARNING)

    def _run():
        try:
            _mcp.run(transport="streamable-http")
        except Exception as e:
            _logger.error(f"MCP server failed: {e}")

    thread = threading.Thread(target=_run, daemon=True, name="inet-mcp-server")
    thread.start()
    _logger.info(f"INET MCP server thread started on port {port}")
    return thread
