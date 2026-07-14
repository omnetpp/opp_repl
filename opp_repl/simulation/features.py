"""
This module provides functionality for interacting with the OMNeT++ feature system.

It wraps the :command:`opp_featuretool` command to query enabled/disabled features,
get compiler/linker flags, folder exclusions, and generate the ``features.h`` header.
"""

import logging
import os
import re
import shlex
import subprocess
import xml.etree.ElementTree as ET

_logger = logging.getLogger(__name__)


class _Feature:
    __slots__ = ("id", "initially_enabled", "ned_packages", "extra_source_folders",
                 "compile_flags", "linker_flags", "requires")

    def __init__(self, elem):
        self.id = elem.get("id", "")
        self.initially_enabled = elem.get("initiallyEnabled", "true").strip().lower() == "true"
        self.ned_packages = elem.get("nedPackages", "").split()
        self.extra_source_folders = elem.get("extraSourceFolders", "").split()
        self.compile_flags = elem.get("compileFlags", "")
        self.linker_flags = elem.get("linkerFlags", "")
        self.requires = elem.get("requires", "").split()


def _parse_oppfeatures(simulation_project):
    """
    Parses ``.oppfeatures`` and returns (root_attrs, list[_Feature]).
    ``root_attrs`` is a dict with ``cppSourceRoots`` (list, possibly empty) and
    ``defines_file`` (string, project-root-relative; default ``src/features.h``).
    Returns (None, []) if no .oppfeatures exists.
    """
    if not has_features(simulation_project):
        return None, []
    path = simulation_project.get_full_path(".oppfeatures")
    root = ET.parse(path).getroot()
    attrs = {
        "cppSourceRoots": root.get("cppSourceRoots", "").split(),
        "defines_file": root.get("definesFile", "src/features.h"),
    }
    features = [_Feature(elem) for elem in root.iter("feature")]
    return attrs, features


def _parse_oppfeaturestate(simulation_project):
    """
    Parses ``.oppfeaturestate`` and returns a {feature_id: bool} dict.
    Returns {} when the file is absent (caller falls back to ``initiallyEnabled``).
    """
    path = simulation_project.get_full_path(".oppfeaturestate")
    if not os.path.isfile(path):
        return {}
    root = ET.parse(path).getroot()
    return {f.get("id"): (f.get("enabled", "true").strip().lower() == "true")
            for f in root.iter("feature") if f.get("id")}


def get_enabled_features(simulation_project):
    """
    Returns ``{feature_id: bool}`` reflecting current enable/disable state.
    Falls back to each feature's ``initiallyEnabled`` when ``.oppfeaturestate``
    is absent or doesn't list the feature.
    """
    _, features = _parse_oppfeatures(simulation_project)
    state = _parse_oppfeaturestate(simulation_project)
    return {f.id: state.get(f.id, f.initially_enabled) for f in features}


def get_disabled_feature_folders(simulation_project):
    """
    Returns a list of project-root-relative folder paths whose contents should
    be skipped at source-collection time because their owning feature is
    disabled.

    For each disabled feature, expands ``nedPackages`` (with dots → slashes,
    prefixed by each ``cppSourceRoots`` entry) and ``extraSourceFolders``
    (taken as-is, project-root-relative). Mirrors the ``-X`` options that
    ``opp_featuretool options -f`` would emit, but reads the XML directly so
    no subprocess is needed.
    """
    attrs, features = _parse_oppfeatures(simulation_project)
    if not features:
        return []
    state = _parse_oppfeaturestate(simulation_project)
    cpp_roots = attrs["cppSourceRoots"] or [""]
    folders = []
    for f in features:
        enabled = state.get(f.id, f.initially_enabled)
        if enabled:
            continue
        for pkg in f.ned_packages:
            pkg_path = pkg.replace(".", "/")
            for root in cpp_roots:
                folders.append(os.path.join(root, pkg_path) if root else pkg_path)
        for extra in f.extra_source_folders:
            folders.append(extra)
    # Dedup while preserving order
    seen = set()
    out = []
    for p in folders:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _read_ned_folder_package(simulation_project, ned_folder):
    """The package declared by ``<ned_folder>/package.ned`` (e.g.
    ``inet.showcases``), ``""`` if the file exists but declares the root
    package, or ``None`` if there is no ``package.ned``."""
    path = simulation_project.get_full_path(os.path.join(ned_folder, "package.ned"))
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"\s*package\s+([\w.]+)\s*;", line)
            if m:
                return m.group(1)
    return ""


def get_disabled_feature_config_folders(simulation_project):
    """
    Project-root-relative folders whose owning feature is disabled, resolved
    through the project's NED folders. Unlike :func:`get_disabled_feature_folders`
    (which expands ``nedPackages`` only under ``cppSourceRoots`` for the C++
    build), this maps each disabled feature's ``nedPackages`` to their real NED
    folder -- e.g. ``inet.showcases.visualizer.osg`` -> ``showcases/visualizer/osg``
    -- so simulation-config collection can drop configs that cannot run because
    their feature (hence their network's NED) is not built.
    """
    _, features = _parse_oppfeatures(simulation_project)
    if not features:
        return []
    state = _parse_oppfeaturestate(simulation_project)
    disabled_packages = []
    for f in features:
        if not state.get(f.id, f.initially_enabled):
            disabled_packages.extend(f.ned_packages)
    if not disabled_packages:
        return []
    ned_folder_base = {}
    for ned_folder in simulation_project.ned_folders:
        pkg = _read_ned_folder_package(simulation_project, ned_folder)
        if pkg is not None:
            ned_folder_base[ned_folder] = pkg
    folders = []
    for dp in disabled_packages:
        # Map the package to a folder via the NED folder with the longest
        # base-package prefix (e.g. "inet.showcases" wins over "inet").
        best_folder = best_base = None
        for ned_folder, base in ned_folder_base.items():
            if dp == base or (base and dp.startswith(base + ".")):
                if best_base is None or len(base) > len(best_base):
                    best_folder, best_base = ned_folder, base
        if best_folder is not None:
            sub = dp[len(best_base):].lstrip(".").replace(".", "/")
            folders.append(os.path.join(best_folder, sub) if sub else best_folder)
    seen = set()
    out = []
    for p in folders:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


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


def _run_featuretool_checked(simulation_project, args):
    """
    Like :py:func:`_run_featuretool` but raises on failure instead of warning.

    Used for mutating commands (``enable``/``disable``) where a silent failure
    would leave the project in the wrong feature state and reintroduce subtle
    "network not found" / missing-symbol errors at run time.
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
        raise Exception(f"opp_featuretool {' '.join(args)} failed "
                        f"(exit {result.returncode}): {result.stderr.strip()}")
    return result.stdout


# OMNeT++ build capabilities (Makefile.inc variable) mapped to the project
# features that require them. "enable all" would turn these features on even
# when the OMNeT++ build lacks the capability, which then fails the project
# build (e.g. INET's makefrag aborts with "Please rebuild OMNeT++ with OSG
# support"). When the capability is absent we re-disable the dependent feature;
# opp_featuretool cascades that to its own dependents (e.g.
# VisualizationOsgShowcases). Features not present in a project are ignored.
_CAPABILITY_GATED_FEATURES = {
    "WITH_OSG": ("VisualizationOsg",),
    "WITH_OSGEARTH": ("VisualizationOsgEarth",),
}


def _get_unsupported_capability_features(simulation_project, existing_feature_ids):
    """
    Returns the existing feature ids whose required OMNeT++ build capability
    (``WITH_OSG`` etc., read from the OMNeT++ ``Makefile.inc``) is not available
    in the OMNeT++ build this project uses. Empty when the capability state
    cannot be determined (in which case the features are left enabled).
    """
    get_omnetpp_project = getattr(simulation_project, "get_omnetpp_project", None)
    omnetpp_project = get_omnetpp_project() if get_omnetpp_project else None
    if omnetpp_project is None:
        return []
    try:
        config = omnetpp_project.get_makefile_inc_config()
    except Exception as e:
        _logger.warning("Could not read OMNeT++ Makefile.inc to detect build "
                        "capabilities; leaving capability-gated features enabled: %s", e)
        return []
    unsupported = []
    for capability_var, feature_ids in _CAPABILITY_GATED_FEATURES.items():
        if config.get(capability_var, "no").strip().lower() != "yes":
            unsupported += [f for f in feature_ids if f in existing_feature_ids]
    return unsupported


def enable_all_features(simulation_project, keep_disabled=("SelfDoc",)):
    """
    Enables all of the project's features, then re-disables the ones that must
    stay off: ``keep_disabled`` (``SelfDoc`` by default, which is build-
    unfriendly) plus any feature whose required OMNeT++ build capability is
    missing (e.g. ``VisualizationOsg`` when OMNeT++ was built without OSG).

    This is the policy that ``run_release_tests`` has always applied before
    building; factoring it out lets the standalone build step apply it too, so
    every test kind runs against a fully-featured build: each feature's NED
    packages stay on the NED path (no ``.nedexclusions`` surprises such as the
    excluded ``inet.validation.tsn`` package) and all feature-gated C++ gets
    compiled. No-op for projects without an ``.oppfeatures`` file.

    Note: this deliberately must NOT be called on the ``feature`` test-kind
    path, which toggles individual features on purpose.
    """
    if not has_features(simulation_project):
        return
    # Only re-disable features that actually exist in this project: the set of
    # "build-unfriendly" features (e.g. SelfDoc) varies across project versions,
    # and asking opp_featuretool to disable an unknown feature is a hard error.
    _, features = _parse_oppfeatures(simulation_project)
    existing = {f.id for f in features}
    to_disable = [f for f in keep_disabled if f in existing]
    to_disable += _get_unsupported_capability_features(simulation_project, existing)
    to_disable = list(dict.fromkeys(to_disable))  # de-dup, preserve order
    _logger.info("Enabling all features (keeping %s disabled) for %s",
                 ", ".join(to_disable) or "none", simulation_project.get_name())
    # -f keeps opp_featuretool non-interactive (it otherwise prompts before
    # disabling a feature that has enabled dependents) and cascades the change.
    _run_featuretool_checked(simulation_project, ["enable", "-f", "all"])
    for feature_id in to_disable:
        _run_featuretool_checked(simulation_project, ["disable", "-f", feature_id])
