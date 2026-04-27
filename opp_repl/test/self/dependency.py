#!/usr/bin/env python3
"""
Tests that opp_repl can be successfully imported with various combinations
of optional dependencies installed:
  1. No optional modules
  2. Each single optional module group individually
  3. All optional modules together

Each scenario is tested in an isolated Python virtual environment that is
cleaned up afterwards.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

OPTIONAL_GROUPS = ["mcp", "cluster", "chart", "optimize", "github", "ide"]


def _venv_python(venv_dir):
    return os.path.join(venv_dir, "bin", "python")


def _create_venv(venv_dir):
    subprocess.check_call(
        [sys.executable, "-m", "venv", venv_dir],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _install(venv_dir, extras=None):
    """Install opp_repl into *venv_dir*, optionally with extras like ``.[chart]``."""
    python = _venv_python(venv_dir)
    spec = PROJECT_DIR if extras is None else f"{PROJECT_DIR}[{extras}]"
    subprocess.check_call(
        [python, "-m", "pip", "install", "--quiet", spec],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _test_import(venv_dir):
    """Return True if ``import opp_repl`` succeeds in the venv."""
    python = _venv_python(venv_dir)
    result = subprocess.run(
        [python, "-c", "import opp_repl"],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


class TestOptionalImports(unittest.TestCase):
    """Each test creates an isolated venv, installs opp_repl with a specific
    set of extras, verifies that ``import opp_repl`` succeeds, and tears
    the venv down."""

    def _run_scenario(self, extras=None):
        label = extras if extras else "no extras"
        venv_dir = tempfile.mkdtemp(prefix="opp_repl_test_")
        try:
            _create_venv(venv_dir)
            _install(venv_dir, extras)
            rc, stdout, stderr = _test_import(venv_dir)
            self.assertEqual(
                rc, 0,
                f"'import opp_repl' failed with extras={label}.\n"
                f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}",
            )
        finally:
            shutil.rmtree(venv_dir, ignore_errors=True)

    # -- no optional dependencies -----------------------------------------

    def test_no_optional_modules(self):
        self._run_scenario(extras=None)

    # -- one optional group at a time -------------------------------------

    def test_optional_mcp(self):
        self._run_scenario(extras="mcp")

    def test_optional_cluster(self):
        self._run_scenario(extras="cluster")

    def test_optional_chart(self):
        self._run_scenario(extras="chart")

    def test_optional_optimize(self):
        self._run_scenario(extras="optimize")

    def test_optional_github(self):
        self._run_scenario(extras="github")

    def test_optional_ide(self):
        self._run_scenario(extras="ide")

    # -- all optional dependencies ----------------------------------------

    def test_all_optional_modules(self):
        self._run_scenario(extras="all")


if __name__ == "__main__":
    unittest.main()
