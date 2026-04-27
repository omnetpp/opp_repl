import builtins
import functools
import glob
import logging
import os
import re

try:
    import omnetpp.scave.analysis
except ImportError:
    pass

from opp_repl.simulation.project import *

_logger = logging.getLogger(__name__)

def export_charts(simulation_project=None, **kwargs):
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    workspace = omnetpp.scave.analysis.Workspace(get_workspace_path("."), [])
    for analysis_file_name in simulation_project.get_analysis_files(**kwargs):
        try:
            _logger.info("Exporting charts, analysis file = " + analysis_file_name)
            analysis = omnetpp.scave.analysis.load_anf_file(simulation_project.get_full_path(analysis_file_name))
            for chart in analysis.collect_charts():
                try:
                    folder = os.path.dirname(simulation_project.get_full_path(analysis_file_name))
                    analysis.export_image(chart, folder, workspace, format="png", dpi=150, target_folder="doc/media")
                except Exception as e:
                    _logger.error("Failed to export chart: " + str(e))
        except Exception as e:
            _logger.error("Failed to load analysis file: " + str(e))

def generate_charts(**kwargs):
    clean_simulations_results(**kwargs)
    create_statistical_results(**kwargs)
    export_charts(**kwargs)
