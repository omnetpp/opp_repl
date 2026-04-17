import argparse
import IPython
import logging
# import omnetpp

# from omnetpp.scave.analysis import *
# from omnetpp.scave.results import *

from opp_repl.common import *
from opp_repl.project.omnetpp import *
from opp_repl.simulation import *
from opp_repl.test.fingerprint import *
# from opp_repl.test import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

def parse_run_repl_arguments():
    description = "Starts the OMNeT++ Python read-eval-print-loop."
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--simulation-project", default=None, help="specifies the name of the project")
    parser.add_argument("-l", "--log-level", choices=["ERROR", "WARN", "INFO", "DEBUG"], default="INFO", help="specifies the log level for the root logging category")
    parser.add_argument("--external-command-log-level", choices=["ERROR", "WARN", "INFO", "DEBUG"], default="WARN", help="specifies the log level for the external command logging categories")
    parser.add_argument("--mcp-port", type=int, default=9966, help="port for the MCP server (0 to disable)")
    parser.add_argument("--handle-exception", default=True, action=argparse.BooleanOptionalAction, help="disables displaying stacktraces for exceptions")
    return parser.parse_args(sys.argv[1:])

def process_run_repl_arguments(args):
    initialize_logging(args.log_level, args.external_command_log_level, None)
    logging.getLogger("distributed.deploy.ssh").setLevel(args.log_level)
    define_omnetpp_sample_projects()
    simulation_project = determine_default_simulation_project(name=args.simulation_project, required=False)

def run_repl_main():
    try:
        args = parse_run_repl_arguments()
        kwargs = process_run_repl_arguments(args)
        if "-h" in sys.argv:
            sys.exit(0)
        else:
            if args.mcp_port != 0:
                from opp_repl.common.mcp import start_mcp_server
                start_mcp_server(port=args.mcp_port)
            app = IPython.terminal.ipapp.TerminalIPythonApp.instance()
            app.interactive_shell_class = TerminalInteractiveShell
            app.display_banner = False
            app.exec_lines = ["import opp_repl", "from opp_repl import *", "enable_autoreload()", "import_user_module()"] # "register_key_bindings()"
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
