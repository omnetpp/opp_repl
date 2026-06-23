"""
Generic entry point for project-specific validation tests.

Validation tests check simulation results against analytical models (often
from research papers) or against results from other simulation frameworks.
They are inherently project-specific, so opp_repl does not implement them
itself. Instead a project declares a ``validation_test_runner`` in its ``.opp``
definition -- a ``"module.path:function"`` dotted reference -- and the generic
:py:func:`run_validation_tests` below resolves and calls it. This lets a driver
like opp_ci run a ``validation`` test kind uniformly across projects, the same
way the other ``run_*_tests`` entry points work.
"""

import importlib
import logging
import os
import sys

from opp_repl.simulation import *
# Imported explicitly as well: when this module is loaded as part of the
# opp_repl.test package, the wildcard import above does not reliably bind this
# name (import ordering), so reference it directly from its defining module.
from opp_repl.simulation.workspace import get_default_simulation_project

_logger = logging.getLogger(__name__)

def _resolve_validation_test_runner(simulation_project):
    spec = getattr(simulation_project, "validation_test_runner", None)
    if not spec:
        raise ValueError(
            f"Simulation project {simulation_project.name!r} does not declare a "
            "'validation_test_runner' in its .opp definition; validation tests are "
            "project-specific, so opp_repl has nothing generic to run.")
    module_name, separator, function_name = spec.partition(":")
    if not separator or not function_name:
        raise ValueError(
            f"Invalid validation_test_runner {spec!r} for project "
            f"{simulation_project.name!r}; expected 'module.path:function'.")
    # The project's own Python package (e.g. inet/python) is usually not on
    # PYTHONPATH when opp_repl is driven as a console script, so make its
    # python_folders importable before resolving the runner.
    for python_folder in simulation_project.python_folders:
        full_path = simulation_project.get_full_path(python_folder)
        if os.path.isdir(full_path) and full_path not in sys.path:
            sys.path.insert(0, full_path)
    module = importlib.import_module(module_name)
    return getattr(module, function_name)

def run_validation_tests(simulation_project=None, **kwargs):
    """
    Runs the validation tests of the given (or default) simulation project.

    Validation tests are project-specific, so the actual runner is resolved
    from the simulation project's ``validation_test_runner`` (declared in its
    ``.opp`` definition) and invoked with the given filter criteria.

    Parameters:
        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>` or None):
            The simulation project whose validation tests to run. Defaults to
            the workspace's default simulation project when not specified
            (mirroring :py:func:`get_simulation_tasks <opp_repl.simulation.task.get_simulation_tasks>`).

        kwargs (dict):
            The filter criteria parameters are forwarded to the resolved
            project-specific validation-test runner.

    Returns (:py:class:`MultipleTestTaskResults <opp_repl.test.task.MultipleTestTaskResults>`):
        the result of running the matching validation test tasks.
    """
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    runner = _resolve_validation_test_runner(simulation_project)
    _logger.debug("Resolved validation test runner %r for project %r",
                  simulation_project.validation_test_runner, simulation_project.name)
    return runner(simulation_project=simulation_project, **kwargs)
