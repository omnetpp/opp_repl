"""
This module provides functionality for interacting with the OMNeT++ feature system.

It wraps the :command:`opp_featuretool` command to query enabled/disabled features,
get compiler/linker flags, folder exclusions, and generate the ``features.h`` header.
"""

import logging
import os
import shlex
import subprocess

_logger = logging.getLogger(__name__)


def has_features(simulation_project):
    """
    Returns True if the simulation project has an ``.oppfeatures`` file.
    """
    oppfeatures_path = simulation_project.get_full_path(".oppfeatures")
    return oppfeatures_path is not None and os.path.isfile(oppfeatures_path)


def get_feature_cflags(simulation_project):
    """
    Returns a list of compiler flags derived from enabled features.

    Calls ``opp_featuretool options -c`` which outputs flags like
    ``-DINET_WITH_AODV -DINET_WITH_BGPv4 ...``

    Parameters:
        simulation_project: The simulation project with .oppfeatures.

    Returns (list of str):
        Compiler flags, or empty list if no .oppfeatures exists.
    """
    if not has_features(simulation_project):
        return []
    output = _run_featuretool(simulation_project, ["options", "-c"])
    return shlex.split(output) if output.strip() else []


def get_feature_ldflags(simulation_project):
    """
    Returns a list of linker flags derived from enabled features.

    Calls ``opp_featuretool options -l``.

    Parameters:
        simulation_project: The simulation project with .oppfeatures.

    Returns (list of str):
        Linker flags, or empty list if no .oppfeatures exists.
    """
    if not has_features(simulation_project):
        return []
    output = _run_featuretool(simulation_project, ["options", "-l"])
    return shlex.split(output) if output.strip() else []


def get_feature_folder_exclusions(simulation_project):
    """
    Returns a list of excluded folder options derived from disabled features.

    Calls ``opp_featuretool options -f`` which outputs flags like
    ``-Xinet/routing/aodv -Xinet/routing/gpsr ...``

    Parameters:
        simulation_project: The simulation project with .oppfeatures.

    Returns (list of str):
        Folder paths (without the -X prefix) to exclude from source collection,
        or empty list if no .oppfeatures exists.
    """
    if not has_features(simulation_project):
        return []
    output = _run_featuretool(simulation_project, ["options", "-f"])
    flags = shlex.split(output) if output.strip() else []
    # Strip -X prefix from each flag
    return [f[2:] if f.startswith("-X") else f for f in flags]


def generate_features_header(simulation_project):
    """
    Generates the ``features.h`` file by calling ``opp_featuretool defines``.

    The output path is read from the ``.oppfeatures`` file's ``definesFile`` attribute.

    Parameters:
        simulation_project: The simulation project with .oppfeatures.

    Returns (str or None):
        The path to the generated file, or None if no .oppfeatures exists.
    """
    if not has_features(simulation_project):
        return None
    # Determine output path from .oppfeatures
    import xml.etree.ElementTree as ET
    oppfeatures_path = simulation_project.get_full_path(".oppfeatures")
    tree = ET.parse(oppfeatures_path)
    root = tree.getroot()
    defines_file = root.get("definesFile", "src/features.h")
    output_path = simulation_project.get_full_path(defines_file)

    # Generate content
    output = _run_featuretool(simulation_project, ["defines"])

    # Write atomically (only if changed)
    output_dir = os.path.dirname(output_path)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    tmp_path = output_path + ".tmp"
    with open(tmp_path, "w") as f:
        f.write(output)
    if os.path.exists(output_path):
        with open(output_path, "r") as f:
            existing = f.read()
        if existing == output:
            os.unlink(tmp_path)
            return output_path
    os.replace(tmp_path, output_path)
    _logger.info("Generated %s", output_path)
    return output_path


def is_feature_enabled(simulation_project, feature_id):
    """
    Returns True if the given feature is enabled in the project.

    Parameters:
        simulation_project: The simulation project with .oppfeatures.
        feature_id (str): The feature ID to check.

    Returns (bool):
        True if enabled, False otherwise.
    """
    if not has_features(simulation_project):
        return False
    # opp_featuretool isenabled uses exit code: 0=enabled, 1=disabled
    return _run_featuretool_exitcode(simulation_project, ["-q", "isenabled", feature_id]) == 0


def resolve_feature_libraries(simulation_project, makefile_inc_config=None):
    """
    Resolves feature-conditional libraries declared in
    ``simulation_project.feature_libraries``.

    For each feature that is enabled, resolves its library spec:

    - ``pkg_config``: runs ``pkg-config --cflags`` and ``pkg-config --libs``
    - ``makefile_inc_libs``: reads variable from Makefile.inc, adds to ldflags
    - ``makefile_inc_flags``: reads variable from Makefile.inc, adds to both cflags and ldflags

    Parameters:
        simulation_project: The simulation project.
        makefile_inc_config: A MakefileIncConfig instance (needed for makefile_inc_* specs).

    Returns (tuple of (list, list)):
        A tuple of (extra_cflags, extra_ldflags) resolved from feature libraries.
    """
    feature_libraries = getattr(simulation_project, 'feature_libraries', None)
    if not feature_libraries:
        return [], []

    extra_cflags = []
    extra_ldflags = []

    for feature_id, spec in feature_libraries.items():
        if not is_feature_enabled(simulation_project, feature_id):
            _logger.debug("Feature %s is disabled, skipping libraries", feature_id)
            continue

        _logger.debug("Feature %s is enabled, resolving libraries: %s", feature_id, spec)

        # pkg-config resolution
        if "pkg_config" in spec:
            pkg_names = spec["pkg_config"]
            cflags, ldflags = _resolve_pkg_config(pkg_names)
            if cflags or ldflags:
                extra_cflags.extend(cflags)
                extra_ldflags.extend(ldflags)
                # Add explicit defines only when pkg-config succeeds
                if "defines" in spec:
                    extra_cflags.extend(f"-D{d}" for d in spec["defines"])
            else:
                _logger.warning("pkg-config packages not found for feature %s: %s", feature_id, pkg_names)

        # Makefile.inc variable → ldflags only
        if "makefile_inc_libs" in spec and makefile_inc_config:
            var_name = spec["makefile_inc_libs"]
            value = makefile_inc_config.get(var_name, "")
            if value:
                extra_ldflags.extend(shlex.split(value))
            else:
                _logger.warning("Makefile.inc variable %s is empty (feature %s)", var_name, feature_id)

        # Makefile.inc variable → both cflags and ldflags
        if "makefile_inc_flags" in spec and makefile_inc_config:
            var_name = spec["makefile_inc_flags"]
            value = makefile_inc_config.get(var_name, "")
            if value:
                flags = shlex.split(value)
                extra_cflags.extend(flags)
                extra_ldflags.extend(flags)
            else:
                _logger.debug("Makefile.inc variable %s is empty (feature %s), skipping", var_name, feature_id)

    return extra_cflags, extra_ldflags


def _resolve_pkg_config(pkg_names):
    """
    Runs pkg-config for the given packages. Returns (cflags, ldflags) lists.
    Returns empty lists if pkg-config fails or packages not found.
    """
    # Check if all packages exist
    try:
        result = subprocess.run(
            ["pkg-config", "--exists"] + pkg_names,
            capture_output=True, text=True
        )
        if result.returncode != 0:
            _logger.warning("pkg-config: packages not found: %s", " ".join(pkg_names))
            return [], []
    except FileNotFoundError:
        _logger.warning("pkg-config not available")
        return [], []

    # Get cflags
    result = subprocess.run(
        ["pkg-config", "--cflags"] + pkg_names,
        capture_output=True, text=True
    )
    cflags = shlex.split(result.stdout.strip()) if result.returncode == 0 else []

    # Get ldflags
    result = subprocess.run(
        ["pkg-config", "--libs"] + pkg_names,
        capture_output=True, text=True
    )
    ldflags = shlex.split(result.stdout.strip()) if result.returncode == 0 else []

    return cflags, ldflags


def _run_featuretool(simulation_project, args):
    """
    Runs opp_featuretool with the given arguments in the project root.

    Returns (str):
        The stdout output of the command.
    """
    cwd = simulation_project.get_full_path(".")
    cmd = ["opp_featuretool"] + args
    _logger.debug("Running: %s in %s", shlex.join(cmd), cwd)

    if simulation_project.opp_env_workspace:
        shell_cmd = "cd " + shlex.quote(cwd) + " && " + shlex.join(cmd)
        cmd = ["opp_env", "-l", "WARN", "run", simulation_project.opp_env_project,
               "-w", simulation_project.opp_env_workspace, "-c", shell_cmd]
        result = subprocess.run(cmd, capture_output=True, text=True)
    else:
        env = simulation_project.get_env()
        result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)

    if result.returncode != 0:
        _logger.warning("opp_featuretool %s failed (exit %d): %s",
                        " ".join(args), result.returncode, result.stderr.strip())
        return ""
    return result.stdout


def _run_featuretool_exitcode(simulation_project, args):
    """
    Runs opp_featuretool and returns the exit code.
    """
    cwd = simulation_project.get_full_path(".")
    cmd = ["opp_featuretool"] + args

    if simulation_project.opp_env_workspace:
        shell_cmd = "cd " + shlex.quote(cwd) + " && " + shlex.join(cmd)
        cmd = ["opp_env", "-l", "WARN", "run", simulation_project.opp_env_project,
               "-w", simulation_project.opp_env_workspace, "-c", shell_cmd]
        result = subprocess.run(cmd, capture_output=True, text=True)
    else:
        env = simulation_project.get_env()
        result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)

    return result.returncode
