"""
This package supports automated testing.

It provides several functions to run various tests:
 - :py:func:`run_chart_tests <opp_repl.test.chart.run_chart_tests()>`: find graphical regressions in plotted charts
 - :py:func:`run_fingerprint_tests <opp_repl.test.fingerprint.task.run_fingerprint_tests()>`: protect against regressions in the simulation trajectory
 - :py:func:`run_smoke_tests <opp_repl.test.smoke.run_smoke_tests()>`: quickly check if simulations run without crashing and terminate properly
 - :py:func:`run_statistical_tests <opp_repl.test.statistical.run_statistical_tests()>`: finds regressions in scalar statistical results
 - :py:func:`run_validation_tests <opp_repl.test.validation.run_validation_tests()>`: compare simulation results to analytical models
"""

import importlib.util

from opp_repl.test.all import *
from opp_repl.test.bisect import *
from opp_repl.test.coverage import *
from opp_repl.test.feature import *
from opp_repl.test.fingerprint import *
from opp_repl.test.opp import *
from opp_repl.test.profile import *
from opp_repl.test.release import *
from opp_repl.test.sanitizer import *
from opp_repl.test.simulation import *
from opp_repl.test.smoke import *
from opp_repl.test.speed import *
from opp_repl.test.statistical import *
from opp_repl.test.task import *

if importlib.util.find_spec("matplotlib"):
    from opp_repl.test.chart import *

__all__ = [k for k,v in locals().items() if k[0] != "_" and v.__class__.__name__ != "module"]

