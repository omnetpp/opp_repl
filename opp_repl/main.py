import argparse
import glob
import importlib.util
import json
import logging
import socket
import sys

from opp_repl.simulation.build import *
from opp_repl.simulation.project import *
from opp_repl.simulation.task import *
from opp_repl.test import *

if importlib.util.find_spec("dask"):
    from opp_repl.common.cluster import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

def parse_run_tasks_arguments(task_name, extra_args_fn=None):
    description = "Runs all " + task_name + " concurrently in the enclosing project, recursively from the current working directory, as separate processes on localhost."
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--load", action="append", default=[], metavar="OPP_FILE", help="load one or more .opp configuration files or directories at startup, can be specified multiple times and supports glob patterns (e.g. --load '*.opp'); when a directory is given, all *.opp files in it are loaded; use --load @opp to load the bundled .opp files shipped with opp_repl; if not specified, all *.opp files in the current working directory are loaded automatically")
    parser.add_argument("-p", "--simulation-project", default=None, help="name of the simulation project to use (auto-detected from the working directory if not specified)")
    parser.add_argument("-m", "--mode", choices=["debug", "release"], help="build mode of the simulation binaries (debug or release)")
    parser.add_argument("--build", action="store_true", help="build the simulation executable before running (default: enabled)")
    parser.add_argument("--no-build", dest="build", action="store_false")
    parser.add_argument("--concurrent", action="store_true", help="run tasks in parallel for faster execution (default: enabled)")
    parser.add_argument("--no-concurrent", dest="concurrent", action="store_false")
    parser.add_argument("--dry-run", action="store_true", help="show what would be done without actually running anything")
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    parser.add_argument("-u", "--user-interface", choices=["Cmdenv", "Qtenv"], default="Cmdenv", help="simulation user interface: Cmdenv for command line, Qtenv for graphical; overrides the value from the INI file (default: Cmdenv)")
    parser.add_argument("-t", "--sim-time-limit", default=None, help="maximum simulation time to run, overrides the value from the INI file (e.g. 10s, 1h)")
    parser.add_argument("-T", "--cpu-time-limit", default=None, help="maximum wall-clock time allowed per simulation (e.g. 300s)")
    parser.add_argument("-f", "--filter", default=None, help="only include simulations matching this regular expression (applies to working directory, INI file, and config name)")
    parser.add_argument("--exclude-filter", default=None, help="exclude simulations matching this regular expression")
    parser.add_argument("-w", "--working-directory-filter", default=None, help="only include simulations from directories matching this regular expression")
    parser.add_argument("--exclude-working-directory-filter", default=None, help="exclude simulations from directories matching this regular expression")
    parser.add_argument("-i", "--ini-file-filter", default=None, help="only include simulations from INI files matching this regular expression")
    parser.add_argument("--exclude-ini-file-filter", default=None, help="exclude simulations from INI files matching this regular expression")
    parser.add_argument("-c", "--config-filter", default=None, help="only include simulations with config names matching this regular expression")
    parser.add_argument("--exclude-config-filter", default=None, help="exclude simulations with config names matching this regular expression")
    parser.add_argument("-r", "--run-number-filter", default=None, help="only include the specified run numbers (e.g. 0, 0..3, 0,2,4)")
    parser.add_argument("--exclude-run-number-filter", default=None, help="exclude the specified run numbers")
    parser.add_argument("--scheduler", choices=["process", "thread", "cluster"], default="thread", help="how to run concurrent tasks: thread (default), process, or cluster for distributed execution")
    parser.add_argument("--simulation-runner", choices=["subprocess", "inprocess"], default="subprocess", help="how to run each simulation: subprocess (default) or inprocess for running within the Python process")
    parser.add_argument("--hosts", default="localhost", help="comma-separated list of hostnames for cluster execution (default: localhost)")
    parser.add_argument("-x", "--nix-shell", default=None, help="name of the Nix shell environment to use on remote cluster nodes")
    parser.add_argument("-b", "--build-engine", choices=["makefile", "task"], default="makefile", help="build engine: makefile uses opp_makemake-generated Makefiles, task uses the built-in task system (default: makefile)")
    parser.add_argument("-l", "--log-level", choices=["ERROR", "WARN", "INFO", "DEBUG"], default="WARN", help="controls the verbosity of log messages (default: WARN)")
    parser.add_argument("--external-command-log-level", choices=["ERROR", "WARN", "INFO", "DEBUG"], default="WARN", help="controls the verbosity of log messages from external commands such as simulations and build tools (default: WARN)")
    parser.add_argument("--log-file", default=None, help="write all log messages to this file (disabled by default)")
    parser.add_argument("--handle-exception", action="store_true", help="display errors as short messages (default: enabled)")
    parser.add_argument("--no-handle-exception", dest="handle_exception", action="store_false")
    parser.add_argument("--result-file", default=None, help="write JSON result to this file; use '-' for stdout (after the text output)")
    parser.set_defaults(concurrent=True, build=True, dry_run=False, handle_exception=True)
    if extra_args_fn is not None:
        extra_args_fn(parser)
    return parser.parse_args(sys.argv[1:])

def process_run_tasks_arguments(args):
    logging.getLogger("distributed.deploy.ssh").setLevel(args.log_level)
    if args.load:
        for opp_file in args.load:
            load_opp_file(opp_file)
    else:
        for opp_file in sorted(glob.glob(os.path.join(os.getcwd(), "*.opp"))):
            load_opp_file(opp_file)
    simulation_project = determine_default_simulation_project(name=args.simulation_project)
    kwargs = {k: v for k, v in vars(args).items() if v is not None}
    kwargs.pop("load", None)
    kwargs.pop("result_file", None)
    kwargs["simulation_project"] = simulation_project
    has_filter_kwarg = False
    for k in kwargs.keys():
        has_filter_kwarg = has_filter_kwarg or k.endswith("filter")
    if not has_filter_kwarg and not args.simulation_project:
        kwargs["working_directory_filter"] = os.path.relpath(os.getcwd(), os.path.realpath(simulation_project.get_full_path(".")))
    if "working_directory_filter" in kwargs:
        kwargs["working_directory_filter"] = re.sub(r"(.*)/$", "\\1", kwargs["working_directory_filter"])
    if args.simulation_runner == "inprocess":
        import omnetpp.cffi
    del kwargs["hosts"]
    if args.hosts != "localhost" and args.hosts != socket.gethostname():
        worker_hostnames = args.hosts.split(",")
        scheduler_hostname = worker_hostnames[0]
        simulation_project.copy_binary_simulation_distribution_to_cluster(worker_hostnames)
        cluster = SSHCluster(scheduler_hostname, worker_hostnames, nix_shell=args.nix_shell)
        cluster.start()
        kwargs["scheduler"] = "cluster"
        kwargs["cluster"] = cluster
    return kwargs

def run_tasks_main(main_function, task_name):
    try:
        args = parse_run_tasks_arguments(task_name)
        initialize_logging(args.log_level, args.external_command_log_level, args.log_file)
        _logger.debug(f"Processing command line arguments: {args}")
        kwargs = process_run_tasks_arguments(args)
        _logger.debug(f"Calling main function with: {kwargs}")
        result = main_function(**kwargs)
        _logger.debug(f"Main function returned: {result}")
        print(result)
        if args.result_file:
            if args.result_file == "-":
                print(json.dumps(result.to_dict(), default=str))
            else:
                with open(args.result_file, "w") as f:
                    json.dump(result.to_dict(), f, default=str)
        sys.exit(0 if (result is None or result.is_all_results_expected()) else 1)
    except KeyboardInterrupt:
        _logger.warn("Program interrupted by user")
    except Exception as e:
        if args.handle_exception:
            _logger.error(str(e))
            sys.exit(1)
        else:
            raise e

def run_simulations_main():
    run_tasks_main(run_simulations, "simulations")

def run_smoke_tests_main():
    run_tasks_main(run_smoke_tests, "smoke tests")

def run_fingerprint_tests_main():
    run_tasks_main(run_fingerprint_tests, "fingerprint tests")

def run_chart_tests_main():
    run_tasks_main(run_chart_tests, "chart tests")

def run_feature_tests_main():
    run_tasks_main(run_feature_tests, "feature tests")

def run_sanitizer_tests_main():
    run_tasks_main(run_sanitizer_tests, "sanitizer tests")

def run_speed_tests_main():
    run_tasks_main(run_speed_tests, "speed tests")

def run_statistical_tests_main():
    run_tasks_main(run_statistical_tests, "statistical tests")

def run_opp_tests_main():
    run_tasks_main(lambda **kwargs: run_opp_tests(test_folder=os.getcwd(), **kwargs), "opp tests")

def run_all_tests_main():
    run_tasks_main(run_all_tests, "tests")

def run_release_tests_main():
    run_tasks_main(run_release_tests, "release tests")

def update_fingerprint_test_results_main():
    run_tasks_main(update_fingerprint_test_results, "update fingerprint test results")

def update_chart_test_results_main():
    run_tasks_main(update_chart_test_results, "update chart test results")

def _module_image_extra_args(parser):
    parser.add_argument("--output-dir", default=None, help="directory the module-image PNGs are written into (required for capture)")
    parser.add_argument("--module-path-filter", default=None, help="glob pattern matched against each module's full path (e.g. '**.host[*]')")
    parser.add_argument("--exclude-module-path-filter", default=None)
    parser.add_argument("--module-type-filter", default=None, help="glob pattern matched against each module's NED type")
    parser.add_argument("--exclude-module-type-filter", default=None)
    parser.add_argument("--group-by", choices=["path", "type", "path_no_indices"], default="path", help="how to group module instances into images (default: path = one per instance)")
    parser.add_argument("--area", choices=["all_elements", "module_rectangle", "viewport"], default="all_elements", help="get_canvas_image area parameter")
    parser.add_argument("--margin", type=int, default=5, help="margin in pixels around the captured area (default: 5)")
    parser.add_argument("--startup-timeout", type=float, default=30.0, help="seconds to wait for each simulation's MCP endpoint (default: 30)")
    parser.add_argument("--metric-threshold", type=float, default=0.0, help="maximum RMSE for a test to pass (default: 0 = pixel-perfect)")

def _module_image_main(main_function, task_name, output_dir_required):
    """Run a module-image task with the standard filter args plus the
    module-image-specific args (which appear in ``--help`` thanks to the
    ``extra_args_fn`` hook in :func:`parse_run_tasks_arguments`)."""
    def add_extra_args(parser):
        _module_image_extra_args(parser)
        parser.add_argument("--baseline-simulation-project", default=None,
                            help="name of the simulation project providing the baseline images (run_module_image_tests only)")
    try:
        args = parse_run_tasks_arguments(task_name, extra_args_fn=add_extra_args)
        initialize_logging(args.log_level, args.external_command_log_level, args.log_file)
        kwargs = process_run_tasks_arguments(args)
        # Translate the module-image-specific args into kwargs.
        for k in ("output_dir", "module_path_filter", "exclude_module_path_filter",
                  "module_type_filter", "exclude_module_type_filter",
                  "group_by", "area", "margin", "startup_timeout",
                  "metric_threshold"):
            v = getattr(args, k, None)
            if v is not None:
                kwargs[k] = v
        if args.baseline_simulation_project:
            ws = get_default_simulation_workspace()
            kwargs["baseline_simulation_project"] = ws.get_simulation_project(
                args.baseline_simulation_project, None)
        # Strip args that don't apply to this main_function.
        if main_function is not run_module_image_tests:
            kwargs.pop("metric_threshold", None)
            kwargs.pop("baseline_simulation_project", None)
        if main_function is not capture_module_images:
            kwargs.pop("output_dir", None)
        if output_dir_required and kwargs.get("output_dir") is None:
            raise Exception("--output-dir is required for this command")
        result = main_function(**kwargs)
        print(result)
        if args.result_file:
            if args.result_file == "-":
                print(json.dumps(result.to_dict(), default=str))
            else:
                with open(args.result_file, "w") as f:
                    json.dump(result.to_dict(), f, default=str)
        sys.exit(0 if (result is None or result.is_all_results_expected()) else 1)
    except KeyboardInterrupt:
        _logger.warn("Program interrupted by user")
    except Exception as e:
        if args.handle_exception:
            _logger.error(str(e))
            sys.exit(1)
        else:
            raise e

def capture_module_images_main():
    _module_image_main(capture_module_images, "module image capture", output_dir_required=True)

def update_module_image_test_results_main():
    _module_image_main(update_module_image_test_results, "update module image baselines", output_dir_required=False)

def run_module_image_tests_main():
    _module_image_main(run_module_image_tests, "module image tests", output_dir_required=False)

def update_statistical_test_results_main():
    run_tasks_main(update_statistical_test_results, "update statistical test results")

def update_speed_test_results_main():
    run_tasks_main(update_speed_test_results, "update speed test results")

def run_self_test_main():
    import unittest
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName("opp_repl.test.self.dependency")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

def parse_build_project_arguments():
    description = "Builds the specified or enclosing simulation project."
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--simulation-project", default=None, help="name of the simulation project to build (auto-detected from the working directory if not specified)")
    parser.add_argument("-m", "--mode", choices=["debug", "release"], help="build mode of the simulation binaries (debug or release)")
    parser.add_argument("--concurrent", default=True, action=argparse.BooleanOptionalAction, help="build multiple targets in parallel for faster compilation (default: enabled)")
    parser.add_argument("-l", "--log-level", choices=["ERROR", "WARN", "INFO", "DEBUG"], default="WARN", help="controls the verbosity of log messages (default: WARN)")
    parser.add_argument("--external-command-log-level", choices=["ERROR", "WARN", "INFO", "DEBUG"], default="INFO", help="controls the verbosity of log messages from build tools and compilers (default: INFO)")
    parser.add_argument("--log-file", default=None, help="write all log messages to this file (disabled by default)")
    parser.add_argument("-b", "--build-engine", choices=["makefile", "task"], default="makefile", help="build engine: makefile uses opp_makemake-generated Makefiles, task uses the built-in task system (default: makefile)")
    parser.add_argument("--handle-exception", default=True, action=argparse.BooleanOptionalAction, help="when enabled, errors are displayed as short messages; use --no-handle-exception to show full stack traces for debugging (default: enabled)")
    parser.add_argument("--load", action="append", default=[], metavar="OPP_FILE", help="load one or more .opp configuration files or directories at startup, can be specified multiple times and supports glob patterns (e.g. --load '*.opp'); when a directory is given, all *.opp files in it are loaded; use --load @opp to load the bundled .opp files shipped with opp_repl; if not specified, all *.opp files in the current working directory are loaded automatically")
    return parser.parse_args(sys.argv[1:])

def process_build_project_arguments(args):
    initialize_logging(args.log_level, args.external_command_log_level, args.log_file)
    if args.load:
        for opp_file in args.load:
            load_opp_file(opp_file)
    else:
        for opp_file in sorted(glob.glob(os.path.join(os.getcwd(), "*.opp"))):
            load_opp_file(opp_file)
    simulation_project = determine_default_simulation_project(name=args.simulation_project)
    kwargs = {k: v for k, v in vars(args).items() if v is not None}
    kwargs.pop("load", None)
    kwargs["simulation_project"] = simulation_project
    return kwargs

def build_project_main():
    try:
        args = parse_build_project_arguments()
        kwargs = process_build_project_arguments(args)
        simulation_project = kwargs.pop("simulation_project")
        result = simulation_project.build(**kwargs)
        if result:
            print(result)
        sys.exit(0 if (result is None or result.is_all_results_expected()) else 1)
    except KeyboardInterrupt:
        _logger.warn("Program interrupted by user")
    except Exception as e:
        if args.handle_exception:
            _logger.error(str(e))
            sys.exit(1)
        else:
            raise e

def parse_build_omnetpp_arguments():
    description = "Builds the specified or default OMNeT++ installation."
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--omnetpp-project", default=None, help="name of the OMNeT++ project to build (uses the workspace default if not specified)")
    parser.add_argument("-m", "--mode", choices=["debug", "release"], help="build mode of the OMNeT++ binaries (debug or release)")
    parser.add_argument("--concurrent", default=True, action=argparse.BooleanOptionalAction, help="build multiple targets in parallel for faster compilation (default: enabled)")
    parser.add_argument("-l", "--log-level", choices=["ERROR", "WARN", "INFO", "DEBUG"], default="WARN", help="controls the verbosity of log messages (default: WARN)")
    parser.add_argument("--external-command-log-level", choices=["ERROR", "WARN", "INFO", "DEBUG"], default="INFO", help="controls the verbosity of log messages from build tools and compilers (default: INFO)")
    parser.add_argument("--log-file", default=None, help="write all log messages to this file (disabled by default)")
    parser.add_argument("-b", "--build-engine", choices=["makefile", "task"], default="makefile", help="build engine: makefile invokes make in the OMNeT++ tree, task uses the built-in task system (default: makefile)")
    parser.add_argument("--handle-exception", default=True, action=argparse.BooleanOptionalAction, help="when enabled, errors are displayed as short messages; use --no-handle-exception to show full stack traces for debugging (default: enabled)")
    parser.add_argument("--load", action="append", default=[], metavar="OPP_FILE", help="load one or more .opp configuration files or directories at startup, can be specified multiple times and supports glob patterns (e.g. --load '*.opp'); when a directory is given, all *.opp files in it are loaded; use --load @opp to load the bundled .opp files shipped with opp_repl; if not specified, all *.opp files in the current working directory are loaded automatically")
    return parser.parse_args(sys.argv[1:])

def _determine_default_omnetpp_project(name=None):
    ws = get_default_simulation_workspace()
    if name:
        projects = ws.get_omnetpp_projects()
        for (proj_name, _), project in projects.items():
            if proj_name == name:
                return project
        raise Exception(f"OMNeT++ project '{name}' is not defined")
    project = ws.get_default_omnetpp_project()
    if project is not None:
        return project
    # Fall back to the OMNeT++ project of an enclosing simulation project (if any)
    sim_project = ws.find_simulation_project_from_current_working_directory()
    if sim_project is not None:
        project = sim_project.get_omnetpp_project()
        if project is not None:
            return project
    raise Exception("No OMNeT++ project is defined; specify one with --omnetpp-project or load an .opp file that defines one")

def process_build_omnetpp_arguments(args):
    initialize_logging(args.log_level, args.external_command_log_level, args.log_file)
    if args.load:
        for opp_file in args.load:
            load_opp_file(opp_file)
    else:
        for opp_file in sorted(glob.glob(os.path.join(os.getcwd(), "*.opp"))):
            load_opp_file(opp_file)
    omnetpp_project = _determine_default_omnetpp_project(name=args.omnetpp_project)
    kwargs = {k: v for k, v in vars(args).items() if v is not None}
    kwargs.pop("load", None)
    kwargs.pop("omnetpp_project", None)
    kwargs["omnetpp_project"] = omnetpp_project
    return kwargs

def build_omnetpp_main():
    try:
        args = parse_build_omnetpp_arguments()
        kwargs = process_build_omnetpp_arguments(args)
        omnetpp_project = kwargs.pop("omnetpp_project")
        result = omnetpp_project.build(**kwargs)
        if result:
            print(result)
        sys.exit(0 if (result is None or result.is_all_results_expected()) else 1)
    except KeyboardInterrupt:
        _logger.warn("Program interrupted by user")
    except Exception as e:
        if args.handle_exception:
            _logger.error(str(e))
            sys.exit(1)
        else:
            raise e

def parse_clean_omnetpp_arguments():
    description = "Cleans the specified or default OMNeT++ installation."
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--omnetpp-project", default=None, help="name of the OMNeT++ project to clean (uses the workspace default if not specified)")
    parser.add_argument("-m", "--mode", choices=["debug", "release"], help="build mode to clean (debug or release)")
    parser.add_argument("-l", "--log-level", choices=["ERROR", "WARN", "INFO", "DEBUG"], default="WARN", help="controls the verbosity of log messages (default: WARN)")
    parser.add_argument("--external-command-log-level", choices=["ERROR", "WARN", "INFO", "DEBUG"], default="INFO", help="controls the verbosity of log messages from build tools (default: INFO)")
    parser.add_argument("--log-file", default=None, help="write all log messages to this file (disabled by default)")
    parser.add_argument("-b", "--build-engine", choices=["makefile", "task"], default="makefile", help="clean engine: makefile uses make clean, task removes build artifacts directly (default: makefile)")
    parser.add_argument("--handle-exception", default=True, action=argparse.BooleanOptionalAction, help="when enabled, errors are displayed as short messages; use --no-handle-exception to show full stack traces for debugging (default: enabled)")
    parser.add_argument("--load", action="append", default=[], metavar="OPP_FILE", help="load one or more .opp configuration files or directories at startup, can be specified multiple times and supports glob patterns (e.g. --load '*.opp'); when a directory is given, all *.opp files in it are loaded; use --load @opp to load the bundled .opp files shipped with opp_repl; if not specified, all *.opp files in the current working directory are loaded automatically")
    return parser.parse_args(sys.argv[1:])

def process_clean_omnetpp_arguments(args):
    initialize_logging(args.log_level, args.external_command_log_level, args.log_file)
    if args.load:
        for opp_file in args.load:
            load_opp_file(opp_file)
    else:
        for opp_file in sorted(glob.glob(os.path.join(os.getcwd(), "*.opp"))):
            load_opp_file(opp_file)
    omnetpp_project = _determine_default_omnetpp_project(name=args.omnetpp_project)
    kwargs = {k: v for k, v in vars(args).items() if v is not None}
    kwargs.pop("load", None)
    kwargs.pop("omnetpp_project", None)
    kwargs["omnetpp_project"] = omnetpp_project
    return kwargs

def clean_omnetpp_main():
    try:
        args = parse_clean_omnetpp_arguments()
        kwargs = process_clean_omnetpp_arguments(args)
        omnetpp_project = kwargs.pop("omnetpp_project")
        result = omnetpp_project.clean(**kwargs)
        if result:
            print(result)
        sys.exit(0)
    except KeyboardInterrupt:
        _logger.warn("Program interrupted by user")
    except Exception as e:
        if args.handle_exception:
            _logger.error(str(e))
            sys.exit(1)
        else:
            raise e

def parse_clean_project_arguments():
    description = "Cleans the specified or enclosing simulation project."
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--simulation-project", default=None, help="name of the simulation project to clean (auto-detected from the working directory if not specified)")
    parser.add_argument("-m", "--mode", choices=["debug", "release"], help="build mode to clean (debug or release)")
    parser.add_argument("-l", "--log-level", choices=["ERROR", "WARN", "INFO", "DEBUG"], default="WARN", help="controls the verbosity of log messages (default: WARN)")
    parser.add_argument("--external-command-log-level", choices=["ERROR", "WARN", "INFO", "DEBUG"], default="INFO", help="controls the verbosity of log messages from build tools (default: INFO)")
    parser.add_argument("--log-file", default=None, help="write all log messages to this file (disabled by default)")
    parser.add_argument("-b", "--build-engine", choices=["makefile", "task"], default="makefile", help="clean engine: makefile uses make clean, task removes build artifacts directly (default: makefile)")
    parser.add_argument("--handle-exception", default=True, action=argparse.BooleanOptionalAction, help="when enabled, errors are displayed as short messages; use --no-handle-exception to show full stack traces for debugging (default: enabled)")
    parser.add_argument("--load", action="append", default=[], metavar="OPP_FILE", help="load one or more .opp configuration files or directories at startup, can be specified multiple times and supports glob patterns (e.g. --load '*.opp'); when a directory is given, all *.opp files in it are loaded; use --load @opp to load the bundled .opp files shipped with opp_repl; if not specified, all *.opp files in the current working directory are loaded automatically")
    return parser.parse_args(sys.argv[1:])

def process_clean_project_arguments(args):
    initialize_logging(args.log_level, args.external_command_log_level, args.log_file)
    if args.load:
        for opp_file in args.load:
            load_opp_file(opp_file)
    else:
        for opp_file in sorted(glob.glob(os.path.join(os.getcwd(), "*.opp"))):
            load_opp_file(opp_file)
    simulation_project = determine_default_simulation_project(name=args.simulation_project)
    kwargs = {k: v for k, v in vars(args).items() if v is not None}
    kwargs.pop("load", None)
    kwargs["simulation_project"] = simulation_project
    return kwargs

def clean_project_main():
    try:
        args = parse_clean_project_arguments()
        kwargs = process_clean_project_arguments(args)
        simulation_project = kwargs.pop("simulation_project")
        result = simulation_project.clean(**kwargs)
        if result:
            print(result)
        sys.exit(0)
    except KeyboardInterrupt:
        _logger.warn("Program interrupted by user")
    except Exception as e:
        if args.handle_exception:
            _logger.error(str(e))
            sys.exit(1)
        else:
            raise e
