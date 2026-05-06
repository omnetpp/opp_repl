"""
This module provides bisecting functionality for simulation tests.

The main entry point is :py:func:`bisect_simulations_between_commits`, which performs a binary search
over a range of git commits to find the first commit that causes a test to change from *good* to *bad*.
Each candidate commit is checked out as a temporary git worktree so that the original working tree is
left untouched.  Stored baseline results (e.g. statistical, fingerprint, speed, chart) are automatically
loaded from the original simulation project via the ``baseline_simulation_project`` parameter, which is
set by default.

Convenience wrappers are provided for each test type:

- :py:func:`bisect_statistical_tests`
- :py:func:`bisect_fingerprint_tests`
- :py:func:`bisect_smoke_tests`
- :py:func:`bisect_chart_tests`
- :py:func:`bisect_sanitizer_tests`
- :py:func:`bisect_speed_tests`
"""

import datetime
import io
import logging
import subprocess
import time

import importlib.util

from opp_repl.common import *
from opp_repl.test.fingerprint import run_fingerprint_tests, update_fingerprint_test_results
from opp_repl.test.sanitizer import run_sanitizer_tests
from opp_repl.test.smoke import run_smoke_tests
from opp_repl.test.speed import run_speed_tests, update_speed_test_results
from opp_repl.test.statistical import run_statistical_tests, update_statistical_test_results

if importlib.util.find_spec("matplotlib"):
    from opp_repl.test.chart import run_chart_tests, update_chart_test_results

_logger = logging.getLogger(__name__)

class BisectResult:
    """Result of bisecting across git commits.

    Attributes:
        offending_commit (str):
            The full git hash of the first commit that causes the result to change.
        result:
            The result object from the offending commit, as returned by ``run_function``.
        num_steps (int):
            The number of bisect steps performed.
        num_commits (int):
            The total number of commits in the search range.
        good_hash (str):
            The original good commit-ish passed by the caller.
        bad_hash (str):
            The original bad commit-ish passed by the caller.
        steps (list):
            A list of ``(commit_hash, result, is_good)`` tuples for every
            commit that was tested during the bisection.
    """

    def __init__(self, offending_commit=None, result=None, num_steps=0, num_commits=0, good_hash=None, bad_hash=None, steps=None, error_message=None, elapsed_wall_time=None):
        self.offending_commit = offending_commit
        self.result = result
        self.num_steps = num_steps
        self.num_commits = num_commits
        self.good_hash = good_hash
        self.bad_hash = bad_hash
        self.steps = steps or []
        self.error_message = error_message
        self.elapsed_wall_time = elapsed_wall_time

    def __repr__(self):
        time_str = " in " + format_timedelta(datetime.timedelta(seconds=self.elapsed_wall_time)) if self.elapsed_wall_time else ""
        if self.error_message:
            return f"Bisect result: {COLOR_RED}ERROR{COLOR_RESET} {self.error_message}{time_str}"
        return (f"Bisect result: offending commit {COLOR_YELLOW}{self.offending_commit[:10]}{COLOR_RESET}"
                f" found in {self.num_steps} steps across {self.num_commits} commits"
                f" ({self.good_hash[:10]}..{self.bad_hash[:10]}){time_str}")

def bisect_simulations_between_commits(simulation_project, good_hash, bad_hash, run_function, good_result="PASS", is_good_result=None, build_log_level="WARN", simulation_log_level="WARN", update_good_results_function=None, **kwargs):
    """Bisect to find the first commit that changes the result of a function.

    Uses binary search: given a good commit and a bad commit, finds the first
    commit that introduced the change.  Each tested commit is checked out as a
    git worktree, leaving the original project folder untouched.

    Parameters:
        simulation_project (:py:class:`SimulationProject`):
            The simulation project whose repository contains both commits.
        good_hash (str):
            A git commit-ish where the result is considered good.
        bad_hash (str):
            A git commit-ish where the result is considered bad.
        run_function (callable):
            A function called as ``run_function(simulation_project=project, **kwargs)``
            that returns a result object for a given project.
        good_result (str):
            The ``result`` attribute value that indicates a good commit.
            Ignored when *is_good_result* is provided.  Default ``"PASS"``.
        is_good_result (callable or None):
            Optional predicate ``is_good_result(result) -> bool``.  When given,
            it is used instead of comparing ``result.result == good_result``.
        kwargs:
            Forwarded to *run_function*.

    Returns:
        :py:class:`BisectResult`
    """
    from opp_repl.simulation.project import make_worktree_simulation_project, _get_git_root

    start_time = time.time()

    if is_good_result is None:
        is_good_result = lambda r: r.result == good_result

    src_root = simulation_project.get_root_path()
    git_root = _get_git_root(src_root)
    rev_list = subprocess.run(
        ["git", "rev-list", "--ancestry-path", f"{good_hash}..{bad_hash}"],
        cwd=git_root, capture_output=True, text=True, check=True,
    )
    commits = rev_list.stdout.strip().split("\n")
    commits = list(reversed(commits))  # oldest first

    num_commits = len(commits)
    _logger.info(f"Bisecting {num_commits} commits between {good_hash} and {bad_hash}")

    steps = []

    def run_and_record(commit, label):
        project = make_worktree_simulation_project(simulation_project, commit)
        run_with_log_levels(project.build, python_log_level=build_log_level)
        run_result = run_with_log_levels(lambda: run_function(simulation_project=project, output_stream=io.StringIO(), **kwargs), python_log_level=simulation_log_level)
        good = is_good_result(run_result)
        steps.append((commit, run_result, good))
        verdict = (COLOR_GREEN + "GOOD" + COLOR_RESET) if good else (COLOR_RED + "BAD" + COLOR_RESET)
        description = run_result.get_summary() if hasattr(run_result, 'get_summary') else str(run_result.result)
        _logger.info(f"{label} {commit[:10]} {verdict} {description}")
        return run_result, good

    # Verify that good_hash is actually good
    good_project = make_worktree_simulation_project(simulation_project, good_hash)
    if update_good_results_function is not None:
        run_with_log_levels(good_project.build, python_log_level=build_log_level)
        run_with_log_levels(lambda: update_good_results_function(simulation_project=good_project, output_stream=io.StringIO(), **kwargs), python_log_level=simulation_log_level)
    kwargs.setdefault("baseline_simulation_project", good_project)
    good_run_result, good_is_good = run_and_record(good_hash, "Verifying good")
    if not good_is_good:
        return BisectResult(good_hash=good_hash, bad_hash=bad_hash, steps=steps,
                            error_message=f"The supposedly good commit {good_hash[:10]} does not pass",
                            elapsed_wall_time=time.time() - start_time)

    # Verify that bad_hash is actually bad
    _, bad_is_good = run_and_record(bad_hash, "Verifying bad ")
    if bad_is_good:
        return BisectResult(good_hash=good_hash, bad_hash=bad_hash, steps=steps,
                            error_message=f"The supposedly bad commit {bad_hash[:10]} actually passes",
                            elapsed_wall_time=time.time() - start_time)

    lo = 0
    hi = num_commits - 1

    while lo < hi:
        mid = (lo + hi) // 2
        commit = commits[mid]
        label = f"Step {len(steps) - 1:>2}/{num_commits}      "

        _, is_good = run_and_record(commit, label)

        if is_good:
            lo = mid + 1
        else:
            hi = mid

    offending_commit = commits[lo]

    already_tested = any(c == offending_commit for c, _, _ in steps)
    if already_tested:
        final_result = next(r for c, r, _ in steps if c == offending_commit)
    else:
        final_result, _ = run_and_record(offending_commit, "Offending     ")

    # Verify the predecessor of the offending commit is good to confirm the transition
    if lo > 0:
        prev_commit = commits[lo - 1]
        prev_tested = any(c == prev_commit for c, _, _ in steps)
        if not prev_tested:
            _, prev_is_good = run_and_record(prev_commit, "Predecessor   ")
            if not prev_is_good:
                _logger.warning(f"Predecessor commit {prev_commit[:10]} also fails — results may be non-monotonic")

    _logger.info(f"Bisect complete: offending commit is {offending_commit[:10]} (found in {len(steps)} steps)")

    return BisectResult(
        offending_commit=offending_commit,
        result=final_result,
        num_steps=len(steps),
        num_commits=num_commits,
        good_hash=good_hash,
        bad_hash=bad_hash,
        steps=steps,
        elapsed_wall_time=time.time() - start_time,
    )

def bisect_statistical_tests(simulation_project, good_hash, bad_hash, update_good_results=True, **kwargs):
    """Bisect to find the first commit that causes statistical tests to fail.

    This is a convenience wrapper around :py:func:`bisect_simulations_between_commits` that uses
    :py:func:`run_statistical_tests` as the run function.

    Parameters:
        simulation_project (:py:class:`SimulationProject`):
            The simulation project whose repository contains both commits.
        good_hash (str):
            A git commit-ish where statistical tests pass.
        bad_hash (str):
            A git commit-ish where statistical tests fail.
        kwargs:
            Forwarded to :py:func:`run_statistical_tests` (e.g.
            ``working_directory_filter``, ``config_filter``, ``run_number``).

    Returns:
        :py:class:`BisectResult`
    """
    return bisect_simulations_between_commits(simulation_project, good_hash, bad_hash,
                  run_function=run_statistical_tests,
                  is_good_result=lambda r: r.is_all_results_expected(),
                  update_good_results_function=update_statistical_test_results if update_good_results else None,
                  **kwargs)
bisect_statistical_tests.__signature__ = combine_signatures(bisect_statistical_tests, bisect_simulations_between_commits, run_statistical_tests)

def bisect_fingerprint_tests(simulation_project, good_hash, bad_hash, update_good_results=True, **kwargs):
    """Bisect to find the first commit that causes fingerprint tests to fail.

    This is a convenience wrapper around :py:func:`bisect_simulations_between_commits` that uses
    :py:func:`run_fingerprint_tests` as the run function.

    Parameters:
        simulation_project (:py:class:`SimulationProject`):
            The simulation project whose repository contains both commits.
        good_hash (str):
            A git commit-ish where fingerprint tests pass.
        bad_hash (str):
            A git commit-ish where fingerprint tests fail.
        kwargs:
            Forwarded to :py:func:`run_fingerprint_tests`.

    Returns:
        :py:class:`BisectResult`
    """
    return bisect_simulations_between_commits(simulation_project, good_hash, bad_hash,
                  run_function=run_fingerprint_tests,
                  is_good_result=lambda r: r.is_all_results_expected(),
                  update_good_results_function=update_fingerprint_test_results if update_good_results else None,
                  **kwargs)
bisect_fingerprint_tests.__signature__ = combine_signatures(bisect_fingerprint_tests, bisect_simulations_between_commits, run_fingerprint_tests)

def bisect_smoke_tests(simulation_project, good_hash, bad_hash, update_good_results=True, **kwargs):
    """Bisect to find the first commit that causes smoke tests to fail.

    This is a convenience wrapper around :py:func:`bisect_simulations_between_commits` that uses
    :py:func:`run_smoke_tests` as the run function.

    Parameters:
        simulation_project (:py:class:`SimulationProject`):
            The simulation project whose repository contains both commits.
        good_hash (str):
            A git commit-ish where smoke tests pass.
        bad_hash (str):
            A git commit-ish where smoke tests fail.
        kwargs:
            Forwarded to :py:func:`run_smoke_tests`.

    Returns:
        :py:class:`BisectResult`
    """
    return bisect_simulations_between_commits(simulation_project, good_hash, bad_hash,
                  run_function=run_smoke_tests,
                  is_good_result=lambda r: r.is_all_results_expected(),
                  **kwargs)
bisect_smoke_tests.__signature__ = combine_signatures(bisect_smoke_tests, bisect_simulations_between_commits, run_smoke_tests)

def bisect_chart_tests(simulation_project, good_hash, bad_hash, update_good_results=True, **kwargs):
    """Bisect to find the first commit that causes chart tests to fail.

    This is a convenience wrapper around :py:func:`bisect_simulations_between_commits` that uses
    :py:func:`run_chart_tests` as the run function.

    Parameters:
        simulation_project (:py:class:`SimulationProject`):
            The simulation project whose repository contains both commits.
        good_hash (str):
            A git commit-ish where chart tests pass.
        bad_hash (str):
            A git commit-ish where chart tests fail.
        kwargs:
            Forwarded to :py:func:`run_chart_tests`.

    Returns:
        :py:class:`BisectResult`
    """
    return bisect_simulations_between_commits(simulation_project, good_hash, bad_hash,
                  run_function=run_chart_tests,
                  is_good_result=lambda r: r.is_all_results_expected(),
                  update_good_results_function=update_chart_test_results if update_good_results else None,
                  **kwargs)
bisect_chart_tests.__signature__ = combine_signatures(bisect_chart_tests, bisect_simulations_between_commits, run_chart_tests)

def bisect_sanitizer_tests(simulation_project, good_hash, bad_hash, update_good_results=True, **kwargs):
    """Bisect to find the first commit that causes sanitizer tests to fail.

    This is a convenience wrapper around :py:func:`bisect_simulations_between_commits` that uses
    :py:func:`run_sanitizer_tests` as the run function.

    Parameters:
        simulation_project (:py:class:`SimulationProject`):
            The simulation project whose repository contains both commits.
        good_hash (str):
            A git commit-ish where sanitizer tests pass.
        bad_hash (str):
            A git commit-ish where sanitizer tests fail.
        kwargs:
            Forwarded to :py:func:`run_sanitizer_tests`.

    Returns:
        :py:class:`BisectResult`
    """
    return bisect_simulations_between_commits(simulation_project, good_hash, bad_hash,
                  run_function=run_sanitizer_tests,
                  is_good_result=lambda r: r.is_all_results_expected(),
                  **kwargs)
bisect_sanitizer_tests.__signature__ = combine_signatures(bisect_sanitizer_tests, bisect_simulations_between_commits, run_sanitizer_tests)

def bisect_speed_tests(simulation_project, good_hash, bad_hash, update_good_results=True, **kwargs):
    """Bisect to find the first commit that causes speed tests to fail.

    This is a convenience wrapper around :py:func:`bisect_simulations_between_commits` that uses
    :py:func:`run_speed_tests` as the run function.

    Parameters:
        simulation_project (:py:class:`SimulationProject`):
            The simulation project whose repository contains both commits.
        good_hash (str):
            A git commit-ish where speed tests pass.
        bad_hash (str):
            A git commit-ish where speed tests fail.
        kwargs:
            Forwarded to :py:func:`run_speed_tests`.

    Returns:
        :py:class:`BisectResult`
    """
    return bisect_simulations_between_commits(simulation_project, good_hash, bad_hash,
                  run_function=run_speed_tests,
                  is_good_result=lambda r: r.is_all_results_expected(),
                  update_good_results_function=update_speed_test_results if update_good_results else None,
                  **kwargs)
bisect_speed_tests.__signature__ = combine_signatures(bisect_speed_tests, bisect_simulations_between_commits, run_speed_tests)
