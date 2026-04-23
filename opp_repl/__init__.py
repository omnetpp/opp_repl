"""
This is the main package for the opp_repl Python library.

It provides sub-packages for running simulations, analyzing simulation results,
generating documentation, automated testing, etc.

See the ``doc/`` directory for detailed guides and usage examples.
"""

import importlib.util

from opp_repl.documentation import *
from opp_repl.simulation import *
from opp_repl.test.fingerprint import *
from opp_repl.test import *

if importlib.util.find_spec("mcp"):
    from opp_repl.common.mcp import *

__all__ = [k for k,v in locals().items() if k[0] != "_" and v.__class__.__name__ != "module"]

