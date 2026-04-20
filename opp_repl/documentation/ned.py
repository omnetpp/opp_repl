import logging
import subprocess

from opp_repl.common import *
from opp_repl.simulation.project import *

_logger = logging.getLogger(__name__)

def generate_ned_documentation(simulation_project, excludes = []):
    _logger.info("Generating NED documentation")
    run_command_with_logging(["opp_neddoc", "--no-automatic-hyperlinks", "-x", ','.join(excludes), simulation_project.get_full_path(".")])
