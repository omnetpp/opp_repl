"""
Test that all 4 omnetpp/inet combinations compile and run under overlays.

Usage from the REPL::

    from test_overlay_build import test_all_overlay_builds
    test_all_overlay_builds()
"""

import logging
import os

from opp_repl.simulation.project import OmnetppProject, SimulationProject
from opp_repl.simulation.overlay import OverlayOmnetppProject, OverlaySimulationProject
from opp_repl.simulation.environment import SimulationEnvironment
from opp_repl.simulation.task import run_simulations

_logger = logging.getLogger(__name__)

def _make_inet_project(name, inet_root):
    return SimulationProject(
        name=name,
        version=None,
        root_folder=inet_root,
        library_folder="src",
        dynamic_libraries=["INET"],
        build_types=["dynamic library"],
        ned_folders=["src", "examples", "showcases", "tutorials", "tests/networks"],
        ini_file_folders=["examples"],
        bin_folder="bin",
    )

def test_overlay_build(env_name, opp_root, inet_root, build_root=None, clean=True):
    """Test one omnetpp + inet combination under overlays.

    Parameters:
        clean (bool): If True, unmount and remove stale overlay state first.

    Returns True on success, raises on failure.
    """
    build_root = build_root or os.path.join(os.path.expanduser("~"), ".opp-test-builds")

    _logger.info("=" * 60)
    _logger.info("Testing: %s", env_name)
    _logger.info("  omnetpp: %s", opp_root)
    _logger.info("  inet:    %s", inet_root)
    _logger.info("=" * 60)

    opp_basename = os.path.basename(opp_root)
    inet_basename = os.path.basename(inet_root)

    overlay_opp = OverlayOmnetppProject(
        OmnetppProject(root_folder=opp_root),
        overlay_key=opp_basename, build_root=build_root,
    )
    inet_proj = _make_inet_project(f"{inet_basename}+{opp_basename}", inet_root)
    overlay_inet = OverlaySimulationProject(
        inet_proj,
        overlay_key=f"{inet_basename}+{opp_basename}",
        omnetpp_project=overlay_opp,
        build_root=build_root,
    )

    if clean:
        for proj in [overlay_opp, overlay_inet]:
            proj._overlay.clean()

    env = SimulationEnvironment(
        env_name,
        omnetpp=overlay_opp,
        simulation_projects=[overlay_inet],
        build_root=build_root,
    )

    _logger.info("[%s] Building...", env_name)
    env.build(mode="release")
    _logger.info("[%s] Build succeeded", env_name)

    _logger.info("[%s] Running simulation...", env_name)
    results = run_simulations(
        simulation_project=overlay_inet,
        working_directory_filter="examples/ethernet/simple",
        run_number=0,
        sim_time_limit="0.1s",
    )
    for r in results.results:
        _logger.info("[%s] Simulation result: %s (reason: %s)", env_name, r.result, getattr(r, "reason", ""))
        if r.result == "ERROR":
            raise RuntimeError(f"[{env_name}] Simulation failed: {r.reason}")
    _logger.info("[%s] OK", env_name)
    return True

def test_all_overlay_builds(workspace=None, build_root=None):
    """Build and run all 4 omnetpp/inet combinations under overlays.

    Parameters:
        workspace (str or None): Path containing omnetpp, omnetpp-baseline,
            inet, inet-baseline directories. Defaults to ``~/workspace``.
        build_root (str or None): Override for the overlay build root.
    """
    workspace = workspace or os.path.join(os.path.expanduser("~"), "workspace")
    build_root = build_root or os.path.join(os.path.expanduser("~"), ".opp-test-builds")

    opp = os.path.join(workspace, "omnetpp")
    opp_bl = os.path.join(workspace, "omnetpp-baseline")
    inet = os.path.join(workspace, "inet")
    inet_bl = os.path.join(workspace, "inet-baseline")

    combinations = [
        ("opp+inet",             opp,    inet),
        ("opp+inet-baseline",    opp,    inet_bl),
        ("opp-bl+inet",          opp_bl, inet),
        ("opp-bl+inet-baseline", opp_bl, inet_bl),
    ]

    results = {}
    for env_name, opp_root, inet_root in combinations:
        try:
            test_overlay_build(env_name, opp_root, inet_root, build_root=build_root)
            results[env_name] = "PASS"
        except Exception as e:
            _logger.exception("[%s] %s", env_name, e)
            results[env_name] = f"FAIL: {e}"

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, status in results.items():
        print(f"  {name:25s} {status}")

    all_passed = all(v == "PASS" for v in results.values())
    print(f"\n{'All 4 combinations PASSED' if all_passed else 'Some combinations FAILED'}")
    return all_passed

def run_simple_example():
    """Run examples/ethernet/simple with all 4 omnetpp/inet overlay combinations."""
    omnetpp_folders = ["omnetpp", "omnetpp-baseline"]
    inet_folders = ["inet", "inet-baseline"]
    for omnetpp_folder in omnetpp_folders:
        omnepp_project = OmnetppProject(root_folder=os.path.expanduser(f"~/workspace/{omnetpp_folder}"))
        omnepp_project.build(mode="release")
        for inet_folder in inet_folders:
            inet_project = SimulationProject(name=inet_folder, version=None, root_folder=os.path.expanduser(f"~/workspace/{inet_folder}"),
                                  library_folder="src", dynamic_libraries=["INET"],
                                  build_types=["dynamic library"],
                                  ned_folders=["src", "examples", "showcases", "tutorials", "tests/networks"],
                                  ini_file_folders=["examples"], bin_folder="bin")
            overlay_inet = OverlaySimulationProject(inet_project,
                overlay_key=f"{omnetpp_folder}+{inet_folder}",
                omnetpp_project=omnepp_project,
            )
            overlay_inet.ensure_mounted()
            overlay_inet.build(mode="release")
            print(f"--- {omnetpp_folder}+{inet_folder} ---")
            results = run_simulations(simulation_project=overlay_inet, working_directory_filter="examples/ethernet/simple")
            print(results)
