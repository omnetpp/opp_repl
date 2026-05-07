"""
This module provides functionality for parsing OMNeT++ Makefile.inc variables.

The main function is :py:func:`get_makefile_vars` which evaluates Makefile.inc
for a given build mode and returns a dictionary of variable values.
"""

import logging
import os
import subprocess
import tempfile

_logger = logging.getLogger(__name__)

# Variables we need from Makefile.inc for building simulation projects.
_MAKEFILE_INC_VARS = [
    "CXX",
    "CC",
    "TOOLCHAIN_NAME",
    "CONFIGNAME",
    "CFLAGS",
    "CXXFLAGS",
    "LDFLAGS",
    "DEFINES",
    "SHLIB_LD",
    "AR_CR",
    "MSGC",
    "LN",
    "MKPATH",
    "SHLIB_POSTPROCESS",
    "OMNETPP_ROOT",
    "OMNETPP_INCL_DIR",
    "OMNETPP_LIB_DIR",
    "OMNETPP_TOOLS_DIR",
    "SHARED_LIB_SUFFIX",
    "A_LIB_SUFFIX",
    "EXE_SUFFIX",
    "LIB_PREFIX",
    "D",
    "KERNEL_LIBS",
    "SYS_LIBS",
    "OPPMAIN_LIB",
    "CMDENV_LIBS",
    "QTENV_LIBS",
    "ALL_ENV_LIBS",
    "IMPORT_DEFINES",
    "WHOLE_ARCHIVE_ON",
    "WHOLE_ARCHIVE_OFF",
    "AS_NEEDED_ON",
    "AS_NEEDED_OFF",
    "PIC_FLAGS",
    "WITH_OSG",
    "WITH_OSGEARTH",
    "WITH_NETBUILDER",
    "OPENMP_FLAGS",
    "LDFLAG_LIBPATH",
    "LDFLAG_INCLUDE",
    "LDFLAG_LIB",
    "PLATFORM",
    "SHARED_LIBS",
]

_SEPARATOR = "===OPP_REPL_SEP==="


def get_makefile_vars(omnetpp_root, mode="release"):
    """
    Evaluates OMNeT++ Makefile.inc for a given build mode and returns variable values.

    This function creates a temporary Makefile that includes Makefile.inc with the
    specified MODE and uses ``make`` to evaluate and print all required variables.

    Parameters:
        omnetpp_root (str):
            Absolute path to the OMNeT++ root directory containing Makefile.inc.

        mode (str):
            Build mode: "release", "debug", "sanitize", "coverage", or "profile".

    Returns (dict):
        A dictionary mapping variable names to their evaluated string values.
    """
    makefile_inc_path = os.path.join(omnetpp_root, "Makefile.inc")
    if not os.path.isfile(makefile_inc_path):
        raise FileNotFoundError(f"Makefile.inc not found at: {makefile_inc_path}")

    # Build a temporary Makefile that includes Makefile.inc and prints variables.
    # MODE is passed on the command line so it overrides the default in Makefile.inc.
    print_lines = []
    for var in _MAKEFILE_INC_VARS:
        print_lines.append(f'\t@echo "$({var})"')
        print_lines.append(f'\t@echo "{_SEPARATOR}"')

    tmp_makefile_content = f"""
include {makefile_inc_path}

.PHONY: _print_vars
_print_vars:
""" + "\n".join(print_lines) + "\n"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".mk", delete=False, dir=omnetpp_root) as tmp:
        tmp.write(tmp_makefile_content)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["make", "-f", tmp_path, "_print_vars", "--no-print-directory", f"MODE={mode}"],
            capture_output=True,
            text=True,
            cwd=omnetpp_root,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to evaluate Makefile.inc (exit code {result.returncode}):\n{result.stderr}"
            )
    finally:
        os.unlink(tmp_path)

    # Parse the output: values separated by _SEPARATOR lines
    output = result.stdout
    parts = output.split(_SEPARATOR + "\n")

    vars_dict = {}
    for i, var in enumerate(_MAKEFILE_INC_VARS):
        if i < len(parts):
            value = parts[i].strip()
            vars_dict[var] = value
        else:
            vars_dict[var] = ""

    _logger.debug("Parsed Makefile.inc variables for mode=%s: %d variables", mode, len(vars_dict))
    return vars_dict


class MakefileIncConfig:
    """
    Cached configuration derived from OMNeT++ Makefile.inc for a specific build mode.

    Attributes provide convenient access to the most commonly used build parameters.
    """

    def __init__(self, omnetpp_root, mode="release"):
        self._vars = get_makefile_vars(omnetpp_root, mode)
        self.mode = mode

    def get(self, var, default=""):
        """Get a raw variable value."""
        return self._vars.get(var, default)

    @property
    def cxx(self):
        return self._vars["CXX"]

    @property
    def cc(self):
        return self._vars["CC"]

    @property
    def toolchain_name(self):
        return self._vars["TOOLCHAIN_NAME"]

    @property
    def configname(self):
        return self._vars["CONFIGNAME"]

    @property
    def cflags(self):
        return self._vars["CFLAGS"]

    @property
    def cxxflags(self):
        return self._vars["CXXFLAGS"]

    @property
    def ldflags(self):
        return self._vars["LDFLAGS"]

    @property
    def defines(self):
        return self._vars["DEFINES"]

    @property
    def shlib_ld(self):
        return self._vars["SHLIB_LD"]

    @property
    def ar_cr(self):
        return self._vars["AR_CR"]

    @property
    def msgc(self):
        return self._vars["MSGC"]

    @property
    def omnetpp_root(self):
        return self._vars["OMNETPP_ROOT"]

    @property
    def omnetpp_incl_dir(self):
        return self._vars["OMNETPP_INCL_DIR"]

    @property
    def omnetpp_lib_dir(self):
        return self._vars["OMNETPP_LIB_DIR"]

    @property
    def omnetpp_tools_dir(self):
        return self._vars["OMNETPP_TOOLS_DIR"]

    @property
    def shared_lib_suffix(self):
        return self._vars["SHARED_LIB_SUFFIX"]

    @property
    def a_lib_suffix(self):
        return self._vars["A_LIB_SUFFIX"]

    @property
    def exe_suffix(self):
        return self._vars["EXE_SUFFIX"]

    @property
    def lib_prefix(self):
        return self._vars["LIB_PREFIX"]

    @property
    def debug_suffix(self):
        """The $D variable: '' for release, '_dbg' for debug, etc."""
        return self._vars["D"]

    @property
    def kernel_libs(self):
        return self._vars["KERNEL_LIBS"]

    @property
    def sys_libs(self):
        return self._vars["SYS_LIBS"]

    @property
    def oppmain_lib(self):
        return self._vars["OPPMAIN_LIB"]

    @property
    def cmdenv_libs(self):
        return self._vars["CMDENV_LIBS"]

    @property
    def qtenv_libs(self):
        return self._vars["QTENV_LIBS"]

    @property
    def all_env_libs(self):
        return self._vars["ALL_ENV_LIBS"]

    @property
    def import_defines(self):
        return self._vars["IMPORT_DEFINES"]

    @property
    def whole_archive_on(self):
        return self._vars["WHOLE_ARCHIVE_ON"]

    @property
    def whole_archive_off(self):
        return self._vars["WHOLE_ARCHIVE_OFF"]

    @property
    def as_needed_on(self):
        return self._vars["AS_NEEDED_ON"]

    @property
    def as_needed_off(self):
        return self._vars["AS_NEEDED_OFF"]

    @property
    def pic_flags(self):
        return self._vars["PIC_FLAGS"]

    @property
    def with_osg(self):
        return self._vars["WITH_OSG"] == "yes"

    @property
    def with_osgearth(self):
        return self._vars["WITH_OSGEARTH"] == "yes"

    @property
    def with_netbuilder(self):
        return self._vars["WITH_NETBUILDER"] == "yes"

    @property
    def openmp_flags(self):
        return self._vars["OPENMP_FLAGS"]

    @property
    def platform(self):
        return self._vars["PLATFORM"]

    @property
    def shared_libs(self):
        return self._vars["SHARED_LIBS"] == "yes"

    @property
    def ldflag_libpath(self):
        return self._vars["LDFLAG_LIBPATH"]

    @property
    def ldflag_include(self):
        return self._vars["LDFLAG_INCLUDE"]

    @property
    def ldflag_lib(self):
        return self._vars["LDFLAG_LIB"]
