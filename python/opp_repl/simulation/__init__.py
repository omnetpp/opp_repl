"""
This package supports running simulations.

The main function is run_simulations() that allows running multiple simulations,
even completely unrelated ones that have different working directories, INI files,
and configurations. The simulations can be run sequentially or concurrently on a
single computer or on an SSH cluster. Besides, the simulations can be run as
separate processes and also in the same Python process loading INET as a library.
"""

from opp_repl.simulation.compare import *
from opp_repl.simulation.environment import *
from opp_repl.simulation.overlay import *
# from opp_repl.simulation.optimize import *
from opp_repl.simulation.project import *
from opp_repl.simulation.task import *

__all__ = [k for k,v in locals().items() if k[0] != "_" and v.__class__.__name__ != "module"]
