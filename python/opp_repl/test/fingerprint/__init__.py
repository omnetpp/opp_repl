"""
This package supports automated fingerprint testing.

The main function is :py:func:`run_fingerprint_tests <opp_repl.test.fingerprint.task.run_fingerprint_tests>`. It allows running multiple fingerprint tests matching
the provided filter criteria.
"""

from opp_repl.test.fingerprint.old import *
from opp_repl.test.fingerprint.store import *
from opp_repl.test.fingerprint.task import *

__all__ = [k for k,v in locals().items() if k[0] != "_" and v.__class__.__name__ != "module"]
