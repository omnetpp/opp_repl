import logging
import os
import shlex

from opp_repl.common import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

class OppEnvSimulationRunner:
    def run(self, simulation_task, args):
        simulation_config = simulation_task.simulation_config
        simulation_project = simulation_config.simulation_project
        working_directory = simulation_config.working_directory
        full_working_directory = simulation_project.get_full_path(working_directory)
        return self.run_args(simulation_project, args, cwd=full_working_directory, wait=simulation_task.wait)

    def run_args(self, simulation_project, args, cwd=None, wait=True):
        shell_cmd = ("cd " + shlex.quote(cwd) + " && " if cwd else "") + shlex.join(args)
        opp_env_args = ["opp_env", "run", simulation_project.opp_env_project, "-w", simulation_project.opp_env_workspace, "-c", shell_cmd]
        return run_command_with_logging(opp_env_args, wait=wait)
