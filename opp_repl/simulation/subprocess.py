import logging

from opp_repl.common import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

def set_subprocess_simulation_runner_log_level(log_level):
    _logger.setLevel(log_level)

class SubprocessSimulationRunner:
    def run(self, simulation_task, args):
        simulation_config = simulation_task.simulation_config
        simulation_project = simulation_config.simulation_project
        working_directory = simulation_config.working_directory
        full_working_directory = simulation_project.get_full_path(working_directory)
        return run_command_with_logging(args, cwd=full_working_directory, env=simulation_project.get_env(), wait=simulation_task.wait, command_line_logger=_logger)