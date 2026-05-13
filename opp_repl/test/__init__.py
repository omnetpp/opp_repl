"""
This package supports automated testing including smoke tests,
fingerprint tests, statistical tests, chart tests, speed tests,
sanitizer tests, feature tests, release tests, coverage reports,
and profiling.
"""

import importlib.util

from opp_repl.test.all import *
from opp_repl.test.bisect import *
from opp_repl.test.comparison import *
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

