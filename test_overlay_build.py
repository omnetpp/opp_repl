from opp_repl.simulation.project import default_workspace
from opp_repl.simulation.task import run_simulations

def run_all_ethernet_simple_examples():
    project_names = [
        "inet+omnetpp",
        "inet+omnetpp-baseline",
        "inet-baseline+omnetpp",
        "inet-baseline+omnetpp-baseline",
    ]
    for project_name in project_names:
        project = default_workspace.get_simulation_project(project_name)
        print(f"--- {project_name} ---")
        results = run_simulations(simulation_project=project, working_directory_filter="examples/ethernet/simple")
        print(results)
