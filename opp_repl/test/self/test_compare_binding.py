"""Regression tests for the simulation-config/project binding used by comparisons.

A SimulationConfig carries the project it was discovered in, and a SimulationTask takes
its executable and every result path from that project — never from the surrounding
`simulation_project` argument. Passing one config list to both sides of a comparison
therefore used to run a single build twice and report IDENTICAL for everything, with
both worktrees dutifully built beforehand (issue #22).

These tests build no simulations and run none; they only inspect how tasks come out
bound. Run directly:

    python -m opp_repl.test.self.test_compare_binding
"""

from opp_repl.simulation.compare import _get_comparison_simulation_tasks, _match_simulation_tasks
from opp_repl.simulation.config import SimulationConfig
from opp_repl.simulation.project import SimulationProject
from opp_repl.simulation.task import get_simulation_tasks
from opp_repl.simulation.workspace import get_default_simulation_project, set_default_simulation_project


def _get_default_simulation_project_or_none():
    try:
        return get_default_simulation_project()
    except Exception:
        return None


def _make_project(name, root_folder, config_names=("General",), working_directory="simulations/demo"):
    simulation_project = SimulationProject(name=name, root_folder=root_folder)
    # Pre-seed discovery so the tests need no checkout on disk.
    simulation_project.simulation_configs = [
        SimulationConfig(simulation_project, working_directory, "omnetpp.ini", config_name, num_runs=1)
        for config_name in config_names]
    simulation_project._simulation_configs_freshness_key = simulation_project._compute_simulation_configs_freshness_key()
    return simulation_project


def _split_comparison_kwargs(**kwargs):
    """The two sides exactly as compare_simulations() collects them."""
    return _get_comparison_simulation_tasks(**kwargs)


def test_explicit_configs_are_selected_for_each_side():
    """Issue #22: one config list passed to both sides must not run one project twice."""
    project_1 = _make_project("demo", "/tmp/wt-commit-aaaa")
    project_2 = _make_project("demo", "/tmp/wt-commit-bbbb")
    project_main = _make_project("demo", "/tmp/main-checkout")

    tasks_1, tasks_2 = _split_comparison_kwargs(
        simulation_project_1=project_1, simulation_project_2=project_2,
        simulation_configs=project_main.get_simulation_configs(), run_number=0)

    root_1 = tasks_1.tasks[0].simulation_config.simulation_project.get_root_path()
    root_2 = tasks_2.tasks[0].simulation_config.simulation_project.get_root_path()
    assert root_1 == "/tmp/wt-commit-aaaa", root_1
    assert root_2 == "/tmp/wt-commit-bbbb", root_2
    assert root_1 != root_2
    # The result folders must be distinct too, or the arms overwrite each other's output.
    assert tasks_1.tasks[0].get_result_folder_full_path() != tasks_2.tasks[0].get_result_folder_full_path()


def test_default_path_without_explicit_configs_still_works():
    """The common case — each side discovers its own configs — must be untouched."""
    project_1 = _make_project("demo", "/tmp/wt-commit-aaaa", config_names=("General", "Other"))
    project_2 = _make_project("demo", "/tmp/wt-commit-bbbb", config_names=("General", "Other"))
    tasks_1, tasks_2 = _split_comparison_kwargs(
        simulation_project_1=project_1, simulation_project_2=project_2, run_number=0)
    assert len(tasks_1.tasks) == 2 and len(tasks_2.tasks) == 2
    assert tasks_1.tasks[0].simulation_config.simulation_project is project_1
    assert tasks_2.tasks[0].simulation_config.simulation_project is project_2
    assert len(_match_simulation_tasks(tasks_1, tasks_2)) == 2


def test_each_arm_gets_its_own_checkouts_config_metadata():
    """Two commits may declare the same config differently; neither may inherit the other's.

    Selection must hand back the *target project's own* config object, not a copy of the
    caller's carrying foreign num_runs/sim_time_limit/expected_result.
    """
    def make(root, **config_kwargs):
        simulation_project = SimulationProject(name="demo", root_folder=root)
        simulation_project.simulation_configs = [
            SimulationConfig(simulation_project, "simulations/demo", "omnetpp.ini", "General", **config_kwargs)]
        simulation_project._simulation_configs_freshness_key = \
            simulation_project._compute_simulation_configs_freshness_key()
        return simulation_project

    project_main = make("/tmp/main-checkout", num_runs=1, sim_time_limit="10s", expected_result="DONE")
    project_1 = make("/tmp/wt-commit-aaaa", num_runs=1, sim_time_limit="99s", expected_result="DONE")
    project_2 = make("/tmp/wt-commit-bbbb", num_runs=1, sim_time_limit="42s", expected_result="ERROR")

    tasks_1, tasks_2 = _split_comparison_kwargs(
        simulation_project_1=project_1, simulation_project_2=project_2,
        simulation_configs=project_main.get_simulation_configs(), run_number=0)

    for tasks, simulation_project, sim_time_limit, expected_result in (
            (tasks_1, project_1, "99s", "DONE"), (tasks_2, project_2, "42s", "ERROR")):
        simulation_config = tasks.tasks[0].simulation_config
        assert simulation_config is simulation_project.simulation_configs[0], "not the target project's own object"
        assert simulation_config.sim_time_limit == sim_time_limit, simulation_config.sim_time_limit
        assert tasks.tasks[0].get_expected_result() == expected_result, tasks.tasks[0].get_expected_result()


def test_config_absent_from_a_checkout_is_not_selected():
    """A config added between the two commits simply is not there to run."""
    project_1 = _make_project("demo", "/tmp/wt-commit-aaaa", config_names=("General", "AddedLater"))
    project_2 = _make_project("demo", "/tmp/wt-commit-bbbb", config_names=("General",))
    _, tasks_2 = _split_comparison_kwargs(
        simulation_project_1=project_1, simulation_project_2=project_2,
        simulation_configs=project_1.get_simulation_configs(), run_number=0)
    configs = [t.simulation_config.config for t in tasks_2.tasks]
    assert configs == ["General"], configs


def test_emulation_config_is_selected_not_dropped():
    """Selection must not re-apply the default filter, which drops emulation/abstract configs."""
    project_1 = SimulationProject(name="demo", root_folder="/tmp/wt-commit-aaaa")
    project_2 = SimulationProject(name="demo", root_folder="/tmp/wt-commit-bbbb")
    for simulation_project in (project_1, project_2):
        simulation_project.simulation_configs = [
            SimulationConfig(simulation_project, "simulations/demo", "omnetpp.ini", "Emu", num_runs=1, emulation=True)]
        simulation_project._simulation_configs_freshness_key = \
            simulation_project._compute_simulation_configs_freshness_key()

    _, tasks_2 = _split_comparison_kwargs(
        simulation_project_1=project_1, simulation_project_2=project_2,
        simulation_configs=project_1.simulation_configs,
        simulation_config_filter=lambda simulation_config: True, run_number=0)
    assert tasks_2.tasks, "the emulation config should still produce a task"
    root = tasks_2.tasks[0].simulation_config.simulation_project.get_root_path()
    assert root == "/tmp/wt-commit-bbbb", root


def test_differing_config_sets_are_matched_not_truncated():
    """The side-only configs must be left out, and the common one still paired correctly."""
    project_1 = _make_project("demo", "/tmp/wt-commit-aaaa", config_names=("AAA", "General"))
    project_2 = _make_project("demo", "/tmp/wt-commit-bbbb", config_names=("General", "ZZZ"))
    tasks_1 = get_simulation_tasks(simulation_project=project_1, run_number=0)
    tasks_2 = get_simulation_tasks(simulation_project=project_2, run_number=0)
    matched = _match_simulation_tasks(tasks_1, tasks_2)
    assert len(matched) == 1, [(a.simulation_config.config, b.simulation_config.config) for a, b in matched]
    task_1, task_2 = matched[0]
    assert task_1.simulation_config.config == task_2.simulation_config.config == "General"
    # ...and each side of the pair still runs in its own checkout.
    assert task_1.simulation_config.simulation_project is project_1
    assert task_2.simulation_config.simulation_project is project_2


def test_positional_pairing_would_have_mis_aligned():
    """Guards the reason matching exists: sorted order alone does not align the two sides."""
    project_1 = _make_project("demo", "/tmp/wt-commit-aaaa", config_names=("AAA", "General"))
    project_2 = _make_project("demo", "/tmp/wt-commit-bbbb", config_names=("General", "ZZZ"))
    tasks_1 = get_simulation_tasks(simulation_project=project_1, run_number=0)
    tasks_2 = get_simulation_tasks(simulation_project=project_2, run_number=0)
    positional = list(zip(tasks_1.tasks, tasks_2.tasks))
    assert any(a.simulation_config.config != b.simulation_config.config for a, b in positional), \
        "expected the positional pairing to mis-align, otherwise this test proves nothing"


def run_tests():
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    run_tests()
