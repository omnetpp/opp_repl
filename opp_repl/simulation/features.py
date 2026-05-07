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
