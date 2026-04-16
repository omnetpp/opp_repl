import os

from opp_repl.simulation.project import SimulationWorkspace
from opp_repl.simulation.task import run_simulations

def run_all_ethernet_simple_examples():
    """
    Run examples/ethernet/simple with all 4 omnetpp/inet overlay combinations.
    Loads project definitions from ``.opp`` files in the workspace.
    """
    workspace = SimulationWorkspace(os.path.expanduser("~/workspace"))
    project_names = [
        "inet+omnetpp",
        "inet+omnetpp-baseline",
        "inet-baseline+omnetpp",
        "inet-baseline+omnetpp-baseline",
    ]
    for project_name in project_names:
        project = workspace.get_simulation_project(project_name)
        print(f"--- {project_name} ---")
        results = run_simulations(simulation_project=project, working_directory_filter="examples/ethernet/simple")
        print(results)
