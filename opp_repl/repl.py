import argparse
import IPython
import logging
import importlib.util
import sys

try:
    import omnetpp
    from omnetpp.scave.analysis import *
    from omnetpp.scave.results import *
except ImportError:
    pass

from opp_repl.common import *
from opp_repl.simulation import *
from opp_repl.test.fingerprint import *
from opp_repl.test import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

def parse_run_repl_arguments():
    description = "Starts the OMNeT++ Python read-eval-print-loop."
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--load", action="append", default=[], metavar="OPP_FILE", help="load one or more .opp configuration files at startup, can be specified multiple times and supports glob patterns (e.g. --load '*.opp')")
    parser.add_argument("-p", "--simulation-project", default=None, help="name of the default simulation project to use (auto-detected from the working directory if not specified)")
    parser.add_argument("--mcp-port", type=int, default=0, help="TCP port for the Model Context Protocol server that allows AI assistants to interact with the REPL (0 to disable, default: 0)")
    parser.add_argument("--mcp-token-hash", default=None, help="SHA-256 hex hash of the bearer token required for MCP authentication (required when --mcp-port is set, unless running inside opp_sandbox)")
    parser.add_argument("-l", "--log-level", choices=["ERROR", "WARN", "INFO", "DEBUG"], default="INFO", help="controls the verbosity of log messages (default: INFO)")
    parser.add_argument("--external-command-log-level", choices=["ERROR", "WARN", "INFO", "DEBUG"], default="WARN", help="controls the verbosity of log messages from external commands such as simulations and build tools (default: WARN)")
    parser.add_argument("--handle-exception", default=True, action=argparse.BooleanOptionalAction, help="when enabled, errors are displayed as short messages; use --no-handle-exception to show full stack traces for debugging (default: enabled)")
    return parser.parse_args(sys.argv[1:])

def process_run_repl_arguments(args):
    initialize_logging(args.log_level, args.external_command_log_level, None)
    logging.getLogger("distributed.deploy.ssh").setLevel(args.log_level)
    for opp_file in args.load:
        load_opp_file(opp_file)
    simulation_project = determine_default_simulation_project(name=args.simulation_project, required=False)

def run_repl_main():
    try:
        args = parse_run_repl_arguments()
        kwargs = process_run_repl_arguments(args)
        if "-h" in sys.argv:
            sys.exit(0)
        else:
            if args.mcp_port != 0:
                try:
                    from opp_repl.common.mcp import start_mcp_server
                    start_mcp_server(port=args.mcp_port, token_hash=args.mcp_token_hash)
                except ImportError:
                    _logger.warning("MCP server not available (install with: pip install opp_repl[mcp])")
            app = IPython.terminal.ipapp.TerminalIPythonApp.instance()
            app.interactive_shell_class = TerminalInteractiveShell
            app.display_banner = False
            app.exec_lines = ["import opp_repl", "from opp_repl import *", "enable_autoreload()", "import_user_module()", "globals().update(get_omnetpp_project_variables())", "globals().update(get_simulation_project_variables())"] # "register_key_bindings()"
            app.initialize(argv=[])
            _logger.info("OMNeT++ Python support is loaded.")
            app.start()
    except KeyboardInterrupt:
        _logger.warn("Program interrupted by user")
    except Exception as e:
        if args.handle_exception:
            _logger.error(str(e))
            sys.exit(1)
        else:
            raise e
