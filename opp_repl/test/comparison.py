"""
Regression-detection tests built on top of the simulation comparison machinery.

Use :py:func:`opp_repl.simulation.compare.compare_simulations` (and its
``_between_commits`` / ``_across_commits`` siblings) when you want to
investigate **why** two simulation runs differ — those return rich
``IDENTICAL`` / ``DIVERGENT`` / ``DIFFERENT`` verdicts together with
divergence positions, cause chains, and statistic-by-statistic tables.

Use the ``run_*_comparison_tests`` functions in this module when you just
need a regression pass/fail.  They run the same comparison pipeline but
report ``PASS`` / ``FAIL`` / ``ERROR`` and integrate with the rest of the
test infrastructure (``num_pass`` / ``num_fail`` counts, ``get_fail_results``,
etc.).

For ``_across_commits`` variants, the ``comparison_mode`` parameter (passed
through to the underlying ``compare_*_across_commits``) decides what each
candidate is tested against:

* ``"differential"`` (default): each commit vs. its predecessor — useful
  for walking a development branch and pinpointing the commit that
  introduced a regression.
* ``"baseline"``: each commit vs. the first one — useful for detecting
  cumulative drift from a reference point without updating any stored
  baseline.

The underlying comparison result is preserved on each
:py:class:`CompareSimulationsTestTaskResult` as ``compare_result`` so callers
can still drill into divergence positions and diff tables after the fact.
"""

# NOTE: this module is reachable during a circular import chain
# (simulation.compare -> test.fingerprint.task -> test/__init__ -> here),
# so simulation.compare is not necessarily fully loaded at import time.
# All references to compare_simulations* are therefore done lazily inside
# the functions; do not pull them in at module scope.

import logging

from opp_repl.common.util import *
from opp_repl.test.task import *

_logger = logging.getLogger(__name__)

_compare_to_test_result = {
    "IDENTICAL": "PASS",
    "DIVERGENT":  "FAIL",
    "DIFFERENT":  "FAIL",
}

class CompareSimulationsTestTaskResult(TestTaskResult):
    """Test-style PASS/FAIL view of a :py:class:`CompareSimulationsTaskResult`.

    The original comparison result is kept on ``compare_result`` so callers
    can still inspect divergence positions or statistic-level differences
    after the test verdict has been determined.
    """
    def __init__(self, compare_result=None, **kwargs):
        result = _compare_to_test_result.get(compare_result.result, compare_result.result)
        super().__init__(task=compare_result.task, result=result, reason=compare_result.reason,
                         elapsed_wall_time=getattr(compare_result, "elapsed_wall_time", None), **kwargs)
        self.compare_result = compare_result

class MultipleCompareSimulationsTestTaskResults(MultipleTestTaskResults):
    """Aggregate test result with the usual PASS/FAIL/ERROR counts."""
    pass

def _wrap_as_test_results(compare_results):
    test_results = [CompareSimulationsTestTaskResult(compare_result=r) for r in compare_results.results]
    return MultipleCompareSimulationsTestTaskResults(
        multiple_tasks=compare_results.multiple_tasks,
        results=test_results,
        elapsed_wall_time=getattr(compare_results, "elapsed_wall_time", None))

# -- Top-level entry points ------------------------------------------------

def run_simulation_comparison_tests(**kwargs):
    """Run a comparison between two projects and report PASS/FAIL/ERROR.

    Thin wrapper around :py:func:`compare_simulations` that converts the
    comparison verdicts into test verdicts.
    """
    from opp_repl.simulation.compare import compare_simulations
    return _wrap_as_test_results(compare_simulations(**kwargs))

def run_simulation_comparison_tests_between_commits(**kwargs):
    """Run a comparison between two git commits and report PASS/FAIL/ERROR.

    Thin wrapper around :py:func:`compare_simulations_between_commits`.
    """
    from opp_repl.simulation.compare import compare_simulations_between_commits
    return _wrap_as_test_results(compare_simulations_between_commits(**kwargs))

def run_simulation_comparison_tests_across_commits(**kwargs):
    """Run comparisons across a sequence of git commits and report PASS/FAIL/ERROR.

    Thin wrapper around :py:func:`compare_simulations_across_commits`.  Per-pair
    ``PASS`` means the candidate commit compares without regression to its
    reference; the reference is chosen by ``comparison_mode``
    (``"differential"`` or ``"baseline"``).
    """
    from opp_repl.simulation.compare import compare_simulations_across_commits
    return _wrap_as_test_results(compare_simulations_across_commits(**kwargs))

# -- Fingerprint-only shorthands -------------------------------------------

def run_fingerprint_comparison_tests(**kwargs):
    """Compare only fingerprint trajectories; report PASS/FAIL/ERROR."""
    return run_simulation_comparison_tests(compare_stdout=False, compare_statistics=False, **kwargs)

def run_fingerprint_comparison_tests_between_commits(**kwargs):
    """Compare only fingerprint trajectories between two commits; report PASS/FAIL/ERROR."""
    return run_simulation_comparison_tests_between_commits(compare_stdout=False, compare_statistics=False, **kwargs)

def run_fingerprint_comparison_tests_across_commits(**kwargs):
    """Compare only fingerprint trajectories across a sequence of commits; report PASS/FAIL/ERROR."""
    return run_simulation_comparison_tests_across_commits(compare_stdout=False, compare_statistics=False, **kwargs)

# -- Statistics-only shorthands --------------------------------------------

def run_statistical_comparison_tests(**kwargs):
    """Compare only scalar statistical results; report PASS/FAIL/ERROR."""
    return run_simulation_comparison_tests(compare_stdout=False, compare_fingerprint=False, **kwargs)

def run_statistical_comparison_tests_between_commits(**kwargs):
    """Compare only scalar statistical results between two commits; report PASS/FAIL/ERROR."""
    return run_simulation_comparison_tests_between_commits(compare_stdout=False, compare_fingerprint=False, **kwargs)

def run_statistical_comparison_tests_across_commits(**kwargs):
    """Compare only scalar statistical results across a sequence of commits; report PASS/FAIL/ERROR."""
    return run_simulation_comparison_tests_across_commits(compare_stdout=False, compare_fingerprint=False, **kwargs)

# -- Stdout-only shorthands ------------------------------------------------

def run_stdout_comparison_tests(**kwargs):
    """Compare only stdout trajectories; report PASS/FAIL/ERROR."""
    return run_simulation_comparison_tests(compare_fingerprint=False, compare_statistics=False, **kwargs)

def run_stdout_comparison_tests_between_commits(**kwargs):
    """Compare only stdout trajectories between two commits; report PASS/FAIL/ERROR."""
    return run_simulation_comparison_tests_between_commits(compare_fingerprint=False, compare_statistics=False, **kwargs)

def run_stdout_comparison_tests_across_commits(**kwargs):
    """Compare only stdout trajectories across a sequence of commits; report PASS/FAIL/ERROR."""
    return run_simulation_comparison_tests_across_commits(compare_fingerprint=False, compare_statistics=False, **kwargs)
