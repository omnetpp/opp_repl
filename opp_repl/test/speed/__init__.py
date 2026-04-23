"""
This package supports automated speed testing.  Speed tests detect
performance regressions by measuring CPU instruction counts and comparing
them against stored baseline values.  The main functions are
run_speed_tests() and update_speed_test_results().
"""

from opp_repl.test.speed.store import *
from opp_repl.test.speed.task import *

__all__ = [k for k,v in locals().items() if k[0] != "_" and v.__class__.__name__ != "module"]
