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
    """Returns the root directory for overlay builds (default ``~/.omnetpp/build``)."""
    return os.environ.get("OPP_BUILD_ROOT", os.path.expanduser("~/.omnetpp/build"))

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

def clear_build_root(build_root=None):
    """Unmount all overlays and remove the entire build root directory."""
    import shutil
    root = build_root or get_build_root()
    cleanup_overlays(root)
    if os.path.isdir(root):
        shutil.rmtree(root)
        _logger.info("Removed build root %s", root)


def make_overlay_simulation_project(project, overlay_key=None, omnetpp_project=None, build_root=None):
    """Create an overlay-backed copy of a SimulationProject.

    .. deprecated::
        Use ``SimulationProject(..., overlay_key=..., build_root=...)`` instead.
    """
    import copy
    import warnings
    warnings.warn(
        "make_overlay_simulation_project is deprecated; pass overlay_key to SimulationProject() instead",
        DeprecationWarning, stacklevel=2,
    )
    clone = copy.copy(project)
    overlay = OverlayMount(
        project.get_root_path(),
        overlay_key or project.name,
        build_root,
    )
    clone._overlay = overlay
    clone.root_folder = overlay.merged_path
    clone.simulation_configs = None
    if omnetpp_project is not None:
        clone.omnetpp_project = omnetpp_project
    return clone


def make_overlay_omnetpp_project(project, overlay_key=None, build_root=None):
    """Create an overlay-backed copy of an OmnetppProject.

    .. deprecated::
        Use ``OmnetppProject(..., overlay_key=..., build_root=...)`` instead.
    """
    import copy
    import warnings
    warnings.warn(
        "make_overlay_omnetpp_project is deprecated; pass overlay_key to OmnetppProject() instead",
        DeprecationWarning, stacklevel=2,
    )
    root = project.get_root_path()
    clone = copy.copy(project)
    overlay = OverlayMount(
        root,
        overlay_key or os.path.basename(root),
        build_root,
    )
    clone._overlay = overlay
    clone.root_folder = overlay.merged_path
    return clone


# Keep old names as aliases for backward compatibility
OverlaySimulationProject = make_overlay_simulation_project
OverlayOmnetppProject = make_overlay_omnetpp_project
