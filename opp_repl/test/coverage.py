import logging
import os
import re

from opp_repl.common.util import *
from opp_repl.simulation.project import *
from opp_repl.simulation.task import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

def generate_coverage_report(simulation_project=None, output_dir="coverage", mode=None, **kwargs):
    mode = mode or "coverage"
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    project_root = simulation_project.get_full_path(".")
    os.environ["LLVM_PROFILE_FILE"] = "coverage-%p.profraw"
    result = run_simulations(simulation_project=simulation_project, mode=mode, **kwargs)
    profraw_files = os.path.join(project_root, "profraw_files.txt")
    merged_profdata_file = os.path.join(project_root, "merged.profdata")
    pattern = re.compile(r"coverage-.*\.profraw")
    file_names = []
    try:
        with open(profraw_files, "w") as f:
            for root, _, files in os.walk(project_root):
                for file_name in files:
                    if pattern.search(file_name):
                        file_names.append(os.path.join(root, file_name))
                        f.write(os.path.join(root, file_name) + "\n")
        if not file_names:
            raise Exception("No .profraw files found — was the project built with coverage instrumentation?")
        args = ["llvm-profdata", "merge", f"--input-files={profraw_files}", f"-output={merged_profdata_file}"]
        run_command_with_logging(args, command_line_logger=_logger)
        coverage_binary = simulation_project.get_executable(mode=mode)
        output_path = os.path.join(project_root, output_dir)
        args = ["llvm-cov", "show", coverage_binary, f"-instr-profile={merged_profdata_file}", "-format=html", f"-output-dir={output_path}"]
        run_command_with_logging(args, command_line_logger=_logger)
    finally:
        for path in [profraw_files, merged_profdata_file, *file_names]:
            if os.path.exists(path):
                os.remove(path)
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
