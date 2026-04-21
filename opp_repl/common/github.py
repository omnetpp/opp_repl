import logging
import os
import requests

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

def _get_simulation_project(simulation_project):
    if simulation_project is None:
        from opp_repl.simulation.project import get_default_simulation_project
        simulation_project = get_default_simulation_project()
    return simulation_project

def dispatch_workflow(workflow_name, simulation_project=None, ref="master"):
    """
    Dispatches a GitHub Actions workflow.

    Parameters:
        workflow_name (str):
            The workflow file name (e.g. ``"fingerprint-tests.yml"``).

        simulation_project (:py:class:`SimulationProject` or None):
            The simulation project whose ``github_owner`` and ``github_repository``
            attributes identify the target repository.  If ``None``, uses the
            default simulation project.

        ref (str):
            The git ref to run the workflow on.  Defaults to ``"master"``.
    """
    simulation_project = _get_simulation_project(simulation_project)
    owner = simulation_project.github_owner
    repository = simulation_project.github_repository
    if owner is None or repository is None:
        raise ValueError(f"Simulation project {simulation_project.name!r} has no github_owner/github_repository configured")
    github_token = open(os.path.expanduser("~/.ssh/github_repo_token"), "r").read().strip()
    url = f"https://api.github.com/repos/{owner}/{repository}/actions/workflows/{workflow_name}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"token {github_token}"
    }
    response = requests.post(url, json={"ref": ref}, headers=headers)
    if response.status_code != 204:
        raise Exception(f"Error: {response.status_code} - {response.text}")
    _logger.info(f"Dispatched workflow {workflow_name} on {owner}/{repository} ref={ref}")

def dispatch_all_workflows(simulation_project=None, **kwargs):
    """
    Dispatches all GitHub Actions workflows configured for the simulation project.

    The workflow file names are read from the ``github_workflows`` list of the
    simulation project.

    Parameters:
        simulation_project (:py:class:`SimulationProject` or None):
            The simulation project.  If ``None``, uses the default.

        kwargs:
            Forwarded to :py:func:`dispatch_workflow`.
    """
    simulation_project = _get_simulation_project(simulation_project)
    workflows = simulation_project.github_workflows
    if not workflows:
        raise ValueError(f"Simulation project {simulation_project.name!r} has no github_workflows configured")
    for workflow_file in workflows:
        dispatch_workflow(workflow_file, simulation_project=simulation_project, **kwargs)
