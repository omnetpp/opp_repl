"""
This module provides the SimulationEnvironment class and its registry.

A :py:class:`SimulationEnvironment` groups one OMNeT++ project with one or more
simulation projects.  Each project can be either a plain
:py:class:`SimulationProject`/:py:class:`OmnetppProject` (used as-is) or an
:py:class:`OverlaySimulationProject`/:py:class:`OverlayOmnetppProject` (backed
by a fuse-overlayfs mount).

Environments are registered by name for easy reuse across the REPL session.
"""

import logging
import multiprocessing
import re

from opp_repl.common.util import run_command_with_logging
from opp_repl.simulation.overlay import OverlaySimulationProject, OverlayOmnetppProject

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

simulation_environments = {}

def get_simulation_environment(name):
    """Return a registered :py:class:`SimulationEnvironment` by name.

    Raises:
        KeyError: if no environment with *name* exists.
    """
    return simulation_environments[name]

def set_simulation_environment(name, env):
    """Register *env* under *name*."""
    simulation_environments[name] = env

def define_simulation_environment(name, **kwargs):
    """Create a :py:class:`SimulationEnvironment`, register it, and return it."""
    return SimulationEnvironment(name, **kwargs)

# ---------------------------------------------------------------------------
# SimulationEnvironment
# ---------------------------------------------------------------------------

class SimulationEnvironment:
    """A complete build + run environment composed of one OMNeT++ project and
    one or more simulation projects.

    Projects can be plain (direct source-tree access) or overlay-wrapped
    (fuse-overlayfs mount).  The environment is agnostic about the difference;
    it simply calls ``ensure_mounted()`` on projects that support it.

    Parameters:
        name (str):
            Human-readable name, also used as registry key.

        omnetpp:
            An :py:class:`OmnetppProject` or :py:class:`OverlayOmnetppProject`.

        simulation_projects (list):
            A list of :py:class:`SimulationProject` and/or
            :py:class:`OverlaySimulationProject` objects.

        build_root (str or None):
            Override for the overlay build root (only relevant for overlay
            projects; forwarded when the environment itself creates overlays).
    """

    def __init__(self, name, omnetpp, simulation_projects, build_root=None):
        self.name = name
        self.omnetpp = omnetpp
        self.simulation_projects = list(simulation_projects)
        self.build_root = build_root
        set_simulation_environment(name, self)

    # ------------------------------------------------------------------
    # Overlay management
    # ------------------------------------------------------------------

    def ensure_overlays(self):
        """Mount overlays for every overlay-wrapped project (no-op for plain ones)."""
        if hasattr(self.omnetpp, "ensure_mounted"):
            self.omnetpp.ensure_mounted()
        for project in self.simulation_projects:
            if hasattr(project, "ensure_mounted"):
                project.ensure_mounted()

    def cleanup(self):
        """Unmount all overlay-wrapped projects."""
        for project in self.simulation_projects:
            if hasattr(project, "unmount"):
                try:
                    project.unmount()
                except Exception as e:
                    _logger.warning("Failed to unmount %s: %s", project, e)
        if hasattr(self.omnetpp, "unmount"):
            try:
                self.omnetpp.unmount()
            except Exception as e:
                _logger.warning("Failed to unmount omnetpp: %s", e)

    # ------------------------------------------------------------------
    # Project selection
    # ------------------------------------------------------------------

    def get_matching_projects(self, simulation_project_filter=None):
        """Return projects whose name matches *simulation_project_filter*.

        Parameters:
            simulation_project_filter (str or None):
                A regex matched against ``project.name``.  ``None`` matches all.

        Returns:
            list: Matching projects (plain or overlay-wrapped).
        """
        if simulation_project_filter is None:
            return list(self.simulation_projects)
        return [
            p for p in self.simulation_projects
            if re.search(simulation_project_filter, p.name)
        ]

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, mode="release", build_omnetpp=True, **kwargs):
        """Build OMNeT++ and all simulation projects in this environment.

        Ensures overlays are mounted first, then builds OMNeT++ (via ``make``),
        then delegates to each simulation project's ``build()`` method.

        Parameters:
            mode (str): Build mode (``"release"``, ``"debug"``, etc.).
            build_omnetpp (bool): Whether to build OMNeT++ itself. Set to
                ``False`` if OMNeT++ is already built.
        """
        self.ensure_overlays()
        if build_omnetpp:
            self._build_omnetpp(mode=mode)
        for project in self.simulation_projects:
            project.build(mode=mode, **kwargs)

    def _build_omnetpp(self, mode="release"):
        root = self.omnetpp.get_root_path()
        if root is None:
            raise RuntimeError("Cannot build OMNeT++: root path is not set")
        _logger.info("Building OMNeT++ in %s mode at %s", mode, root)
        env = self._get_omnetpp_build_env()
        args = ["make", "MODE=" + mode, "-j", str(multiprocessing.cpu_count())]
        run_command_with_logging(args, cwd=root, env=env, error_message="Building OMNeT++ failed")

    def _get_omnetpp_build_env(self):
        """Return an env dict suitable for building OMNeT++.

        Ensures the omnetpp bin dir is in PATH (required by the Makefile's
        ``check-env`` target).
        """
        import os
        env = os.environ.copy()
        root = self.omnetpp.get_root_path()
        bin_dir = os.path.join(root, "bin")
        lib_dir = os.path.join(root, "lib")
        path_parts = env.get("PATH", "").split(os.pathsep)
        if bin_dir not in path_parts:
            env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        ld_parts = env.get("LD_LIBRARY_PATH", "").split(os.pathsep)
        if lib_dir not in ld_parts:
            env["LD_LIBRARY_PATH"] = lib_dir + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        return env

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def __repr__(self):
        project_names = ", ".join(p.name for p in self.simulation_projects)
        return f"SimulationEnvironment(name={self.name!r}, projects=[{project_names}])"
