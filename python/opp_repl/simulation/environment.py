"""
This module provides the SimulationEnvironment class and its registry.

A :py:class:`SimulationEnvironment` groups one OMNeT++ project with one or more
simulation projects.  Each project can optionally use overlay builds via the
``overlay_key`` parameter on :py:class:`OmnetppProject` and
:py:class:`SimulationProject`.

Environments are registered by name for easy reuse across the REPL session.
"""

import logging
import re

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
            An :py:class:`OmnetppProject` (optionally with ``overlay_key``).

        simulation_projects (list):
            A list of :py:class:`SimulationProject` objects (optionally with
            ``overlay_key``).

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
        self.omnetpp.ensure_mounted()
        for project in self.simulation_projects:
            project.ensure_mounted()

    def cleanup(self):
        """Unmount all overlay-wrapped projects."""
        for project in self.simulation_projects:
            try:
                project.unmount()
            except Exception as e:
                _logger.warning("Failed to unmount %s: %s", project, e)
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

        Ensures overlays are mounted first, then builds OMNeT++ (via
        :py:meth:`OmnetppProject.build`), then delegates to each simulation
        project's ``build()`` method.

        Parameters:
            mode (str): Build mode (``"release"``, ``"debug"``, etc.).
            build_omnetpp (bool): Whether to build OMNeT++ itself. Set to
                ``False`` if OMNeT++ is already built.
        """
        self.ensure_overlays()
        if build_omnetpp:
            self.omnetpp.build(mode=mode)
        for project in self.simulation_projects:
            project.build(mode=mode, **kwargs)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def __repr__(self):
        project_names = ", ".join(p.name for p in self.simulation_projects)
        return f"SimulationEnvironment(name={self.name!r}, projects=[{project_names}])"
