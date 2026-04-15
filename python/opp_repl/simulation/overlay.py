"""
This module provides fuse-overlayfs support for out-of-tree builds.

It contains:

- :py:class:`OverlayMount`: manages a single fuse-overlayfs mount (lower/upper/work/merged dirs).
- :py:class:`OverlaySimulationProject`: proxy wrapper that makes a :py:class:`SimulationProject` appear rooted at an overlay mount.
- :py:class:`OverlayOmnetppProject`: proxy wrapper that makes an :py:class:`OmnetppProject` appear rooted at an overlay mount.
"""

import logging
import os
import subprocess

_logger = logging.getLogger(__name__)

def get_build_root():
    """Returns the root directory for overlay builds (default ``~/.opp-builds``)."""
    return os.environ.get("OPP_BUILD_ROOT", os.path.expanduser("~/.opp-builds"))

class OverlayMount:
    """Manages a single fuse-overlayfs mount point.

    Parameters:
        lower_dir (str): Absolute path to the read-only source tree.
        overlay_key (str): Unique key used as subdirectory name under the build root.
        build_root (str or None): Override for the build root directory.
    """

    def __init__(self, lower_dir, overlay_key, build_root=None):
        self.lower_dir = os.path.realpath(lower_dir)
        self.overlay_key = overlay_key
        self.build_root = build_root or get_build_root()
        self._base_dir = os.path.join(self.build_root, self.overlay_key)
        self.upper_dir = os.path.join(self._base_dir, "upper")
        self.work_dir = os.path.join(self._base_dir, "work")
        self._merged_dir = os.path.join(self._base_dir, "merged")

    @property
    def merged_path(self):
        """Absolute path to the merged (writable) mount point."""
        return self._merged_dir

    def is_mounted(self):
        """Check whether the overlay is currently mounted."""
        try:
            with open("/proc/mounts") as f:
                target = os.path.realpath(self._merged_dir)
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and os.path.realpath(parts[1]) == target:
                        return True
        except OSError:
            pass
        return False

    def mount(self):
        """Create directories and mount the overlay (idempotent).

        Returns:
            str: The merged mount-point path.
        """
        if self.is_mounted():
            _logger.debug("Overlay %s already mounted at %s", self.overlay_key, self._merged_dir)
            return self._merged_dir
        for d in (self.upper_dir, self.work_dir, self._merged_dir):
            os.makedirs(d, exist_ok=True)
        cmd = [
            "fuse-overlayfs",
            "-o", f"lowerdir={self.lower_dir},upperdir={self.upper_dir},workdir={self.work_dir}",
            self._merged_dir,
        ]
        _logger.info("Mounting overlay %s: %s -> %s", self.overlay_key, self.lower_dir, self._merged_dir)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"fuse-overlayfs failed for {self.overlay_key}: {result.stderr.strip()}"
            )
        return self._merged_dir

    def unmount(self):
        """Unmount the overlay (no-op if not mounted)."""
        if not self.is_mounted():
            return
        cmd = ["fusermount", "-u", self._merged_dir]
        _logger.info("Unmounting overlay %s at %s", self.overlay_key, self._merged_dir)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"fusermount -u failed for {self.overlay_key}: {result.stderr.strip()}"
            )

    def clean(self):
        """Unmount (if mounted) and remove the upper/work directories."""
        self.unmount()
        import shutil
        for d in (self.upper_dir, self.work_dir):
            if os.path.isdir(d):
                shutil.rmtree(d)
        _logger.info("Cleaned overlay %s", self.overlay_key)

    def __repr__(self):
        mounted = " MOUNTED" if self.is_mounted() else ""
        return f"OverlayMount(key={self.overlay_key!r}, lower={self.lower_dir!r}{mounted})"


def list_overlays(build_root=None):
    """List overlay keys that have directories under the build root.

    Returns:
        list of str: overlay key names.
    """
    root = build_root or get_build_root()
    if not os.path.isdir(root):
        return []
    return sorted(
        entry for entry in os.listdir(root)
        if os.path.isdir(os.path.join(root, entry, "merged"))
    )

def cleanup_overlays(build_root=None):
    """Unmount all overlays under the build root."""
    root = build_root or get_build_root()
    for key in list_overlays(root):
        merged = os.path.join(root, key, "merged")
        try:
            subprocess.run(["fusermount", "-u", merged], capture_output=True, text=True)
            _logger.info("Unmounted overlay %s", key)
        except Exception as e:
            _logger.warning("Failed to unmount overlay %s: %s", key, e)


def make_overlay_simulation_project(project, overlay_key=None, omnetpp_project=None, build_root=None):
    """Create an overlay-backed copy of a SimulationProject.

    Makes a shallow copy and patches ``root_folder`` and ``omnetpp_project``
    so that all methods naturally resolve paths to the overlay mount point.
    Also overrides ``get_env()`` to include the overlay OMNeT++ bin/lib dirs.

    Parameters:
        project: The original :py:class:`SimulationProject` to copy.
        overlay_key (str or None): Overlay key name. Defaults to ``project.name``.
        omnetpp_project: Optional override for the OMNeT++ project.
        build_root (str or None): Override for the build root directory.

    Returns:
        A copy of *project* whose paths point to the overlay.
    """
    import copy
    overlay = OverlayMount(
        project.get_root_path(),
        overlay_key or project.name,
        build_root,
    )
    clone = copy.copy(project)
    clone._overlay = overlay
    clone.root_folder = overlay.merged_path
    clone.simulation_configs = None
    if omnetpp_project is not None:
        clone.omnetpp_project = omnetpp_project

    original_get_env = type(project).get_env

    def _overlay_get_env(self):
        env = original_get_env(self)
        opp_root = self.omnetpp_project.get_root_path()
        if opp_root is not None:
            bin_dir = os.path.join(opp_root, "bin")
            lib_dir = os.path.join(opp_root, "lib")
            path_parts = env.get("PATH", "").split(os.pathsep)
            if bin_dir not in path_parts:
                env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
            ld_parts = env.get("LD_LIBRARY_PATH", "").split(os.pathsep)
            if lib_dir not in ld_parts:
                env["LD_LIBRARY_PATH"] = lib_dir + os.pathsep + env.get("LD_LIBRARY_PATH", "")
        return env

    import types
    clone.get_env = types.MethodType(_overlay_get_env, clone)

    clone.ensure_mounted = lambda: overlay.mount()
    clone.unmount = lambda: overlay.unmount()
    clone.is_mounted = lambda: overlay.is_mounted()
    return clone


def make_overlay_omnetpp_project(project, overlay_key=None, build_root=None):
    """Create an overlay-backed copy of an OmnetppProject.

    Makes a shallow copy and patches ``root_folder`` so that all methods
    naturally resolve paths to the overlay mount point.

    Parameters:
        project: The original :py:class:`OmnetppProject` to copy.
        overlay_key (str or None): Overlay key name. Defaults to the basename
            of the project's root path.
        build_root (str or None): Override for the build root directory.

    Returns:
        A copy of *project* whose paths point to the overlay.
    """
    import copy
    root = project.get_root_path()
    overlay = OverlayMount(
        root,
        overlay_key or os.path.basename(root),
        build_root,
    )
    clone = copy.copy(project)
    clone._overlay = overlay
    clone.root_folder = overlay.merged_path

    clone.ensure_mounted = lambda: overlay.mount()
    clone.unmount = lambda: overlay.unmount()
    clone.is_mounted = lambda: overlay.is_mounted()
    return clone


# Keep old names as aliases for backward compatibility
OverlaySimulationProject = make_overlay_simulation_project
OverlayOmnetppProject = make_overlay_omnetpp_project
