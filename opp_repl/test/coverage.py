import glob
import logging
import os
import shlex
import shutil
import subprocess

from opp_repl.common.util import *
from opp_repl.simulation.project import *
from opp_repl.simulation.task import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

def get_coverage_tool(simulation_project, name, mode="coverage"):
    """
    Returns the LLVM tool *name* (``llvm-profdata`` or ``llvm-cov``) for the profiles of the project's
    compiler. The raw profile format changes between LLVM versions, so the tool must have the version
    of the compiler. The environment variable ``LLVM_PROFDATA`` or ``LLVM_COV`` wins; then comes
    ``<name>-<major version of the compiler>`` if it is on the ``PATH``; then *name* itself.
    """
    variable = name.upper().replace("-", "_")
    if variable in os.environ:
        return os.environ[variable]
    try:
        compiler = shlex.split(simulation_project.get_omnetpp_project().get_makefile_inc_config(mode=mode).cxx)[-1]
        version = subprocess.run([compiler, "-dumpversion"], capture_output=True, text=True, check=True).stdout.strip()
        versioned_name = name + "-" + version.split(".")[0]
        if shutil.which(versioned_name):
            return versioned_name
    except Exception as e:
        _logger.debug(f"Cannot find the compiler version for {name}: {e}")
    return name

def get_coverage_objects(simulation_project, mode="coverage"):
    """
    Returns the binaries that hold the coverage mapping of the project's own code: its dynamic
    libraries in *mode*, or its executable if it builds no dynamic library.
    """
    if simulation_project.build_types[0] != "dynamic library":
        return [simulation_project.get_executable(mode=mode)]
    makefile_inc_config = simulation_project.get_omnetpp_project().get_makefile_inc_config(mode=mode)
    objects = []
    for library in simulation_project.dynamic_libraries:
        library_folder = simulation_project.get_full_path(simulation_project.library_folder)
        objects.append(os.path.join(library_folder, makefile_inc_config.lib_prefix + library + makefile_inc_config.debug_suffix + makefile_inc_config.shared_lib_suffix))
    return objects

def get_coverage_filter_args(simulation_project):
    """
    Returns the ``llvm-cov`` arguments that restrict a report to the project's C++ folders, without the
    files that match a regular expression of ``exclude`` in the ``report`` aspect of the project's
    ``coverage`` test parameters.
    """
    exclusions = simulation_project.test_parameters.get("coverage", {}).get("report", {}).get("exclude", [])
    exclusion_args = [f"-ignore-filename-regex={'|'.join(exclusions)}"] if exclusions else []
    return exclusion_args + [simulation_project.get_full_path(folder) for folder in simulation_project.cpp_folders]

def clear_coverage_profiles(simulation_project):
    """Removes the profile pool of the project, so that the next coverage runs start a new pool."""
    for file_name in glob.glob(os.path.join(simulation_project.get_coverage_profile_folder(), "*.prof*")):
        os.remove(file_name)

def merge_coverage_profiles(simulation_project, mode="coverage"):
    """Merges the raw profiles of the pool into ``merged.profdata`` in the pool folder, and returns its path."""
    profile_folder = simulation_project.get_coverage_profile_folder()
    profile_files = sorted(glob.glob(os.path.join(profile_folder, "*.profraw")))
    if not profile_files:
        raise Exception(f"No .profraw files in {profile_folder}, was the project built and run in coverage mode?")
    input_list_file = os.path.join(profile_folder, "profraw_files.txt")
    merged_profile_file = os.path.join(profile_folder, "merged.profdata")
    with open(input_list_file, "w") as f:
        f.write("\n".join(profile_files) + "\n")
    args = [get_coverage_tool(simulation_project, "llvm-profdata", mode=mode), "merge", "-sparse", f"--input-files={input_list_file}", f"-output={merged_profile_file}"]
    run_command_with_logging(args, error_message="Merging the coverage profiles failed", command_line_logger=_logger)
    os.remove(input_list_file)
    return merged_profile_file

def rewrite_lcov_text(lcov_text, root_folder, test_name=None):
    """Makes the source paths of an lcov text relative to *root_folder*, and names *test_name* as the test of each record."""
    lines = []
    for line in lcov_text.splitlines():
        if line.startswith("SF:"):
            if test_name:
                lines.append("TN:" + test_name)
            lines.append("SF:" + os.path.relpath(line[3:], root_folder))
        elif not line.startswith("TN:"):
            lines.append(line)
    return "\n".join(lines) + "\n"

def export_coverage(simulation_project=None, output_file="coverage.lcov", test_name=None, mode="coverage"):
    """
    Merges the profile pool of the project, and writes the coverage of its C++ sources as an lcov file.

    The processes of a coverage build add their profiles to the pool (see
    :py:meth:`get_coverage_profile_folder <opp_repl.simulation.project.SimulationProject.get_coverage_profile_folder>`),
    so run any test kinds in coverage mode first. The source paths are relative to the project root.

    Parameters:
        output_file (string):
            The path of the lcov file.

        test_name (string or None):
            The name of the test suite, written as the lcov test name of each record, so that a report
            of several lcov files can give the coverage of each suite.

    Returns (string):
        the path of the lcov file.
    """
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    merged_profile_file = merge_coverage_profiles(simulation_project, mode=mode)
    objects = get_coverage_objects(simulation_project, mode=mode)
    args = [get_coverage_tool(simulation_project, "llvm-cov", mode=mode), "export", "-format=lcov", f"-instr-profile={merged_profile_file}",
            objects[0], *[f"-object={o}" for o in objects[1:]], *get_coverage_filter_args(simulation_project)]
    _logger.info(" ".join(args))
    # the lcov text of a large project has millions of lines, too many for the line logger of run_command_with_logging
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception("Exporting the coverage failed:\n" + result.stderr[-2000:])
    with open(output_file, "w") as f:
        f.write(rewrite_lcov_text(result.stdout, simulation_project.get_full_path("."), test_name))
    return output_file

def generate_coverage_report(simulation_project=None, output_dir="coverage", mode=None, **kwargs):
    mode = mode or "coverage"
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    clear_coverage_profiles(simulation_project)
    result = run_simulations(simulation_project=simulation_project, mode=mode, **kwargs)
    try:
        merged_profile_file = merge_coverage_profiles(simulation_project, mode=mode)
        objects = get_coverage_objects(simulation_project, mode=mode)
        output_path = simulation_project.get_full_path(output_dir)
        args = [get_coverage_tool(simulation_project, "llvm-cov", mode=mode), "show", objects[0], *[f"-object={o}" for o in objects[1:]],
                f"-instr-profile={merged_profile_file}", "-format=html", f"-output-dir={output_path}", *get_coverage_filter_args(simulation_project)]
        run_command_with_logging(args, error_message="Generating the coverage report failed", command_line_logger=_logger)
    finally:
        clear_coverage_profiles(simulation_project)
    return result

def run_coverage_tests(simulation_project=None, output_dir="coverage", **kwargs):
    """
    Runs the simulations with coverage instrumentation and generates an HTML coverage report.

    This is the entry point used from the command line and CI (mirroring the other
    ``run_*_tests`` functions). The HTML report is written under ``output_dir`` in the
    project root; the return value is the underlying simulation results so the caller
    gets a pass/fail verdict.

    Returns (:py:class:`MultipleTaskResults <opp_repl.common.task.MultipleTaskResults>`):
        the results of running the instrumented simulations.
    """
    if simulation_project is not None:
        kwargs["simulation_project"] = simulation_project
    kwargs = apply_project_test_defaults("coverage", kwargs)
    return generate_coverage_report(output_dir=output_dir, **kwargs)
run_coverage_tests.__signature__ = combine_signatures(run_coverage_tests, generate_coverage_report, run_simulations)

def open_coverage_report(simulation_project=None, output_dir="coverage", **kwargs):
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    generate_coverage_report(simulation_project=simulation_project, output_dir=output_dir, **kwargs)
    output_path = os.path.join(simulation_project.get_full_path("."), output_dir)
    open_file_with_default_editor(f"{output_path}/index.html")
