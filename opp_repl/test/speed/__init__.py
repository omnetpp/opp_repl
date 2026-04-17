"""
This package supports automated speed testing.

The main function is :py:func:`run_speed_tests <opp_repl.test.speed.task.run_speed_tests>`. It allows running multiple speed tests matching
the provided filter criteria.
"""

from opp_repl.test.speed.store import *
from opp_repl.test.speed.task import *

__all__ = [k for k,v in locals().items() if k[0] != "_" and v.__class__.__name__ != "module"]
