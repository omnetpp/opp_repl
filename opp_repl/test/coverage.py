import logging
import os
import re

from opp_repl.common.util import *
from opp_repl.simulation.project import *
from opp_repl.simulation.task import *

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

def generate_coverage_report(simulation_project=None, output_dir="coverage", **kwargs):
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    project_root = simulation_project.get_full_path(".")
    os.environ["LLVM_PROFILE_FILE"] = "coverage-%p.profraw"
    run_simulations(simulation_project=simulation_project, mode="coverage", **kwargs)
    profraw_files = os.path.join(project_root, "profraw_files.txt")
    pattern = re.compile(r"coverage-.*\.profraw")
    file_names = []
    with open(profraw_files, "w") as f:
        for root, _, files in os.walk(project_root):
            for file_name in files:
                if pattern.search(file_name):
                    file_names.append(os.path.join(root, file_name))
                    f.write(os.path.join(root, file_name) + "\n")
    if not file_names:
        os.remove(profraw_files)
        raise Exception("No .profraw files found — was the project built with coverage instrumentation?")
    merged_profdata_file = os.path.join(project_root, "merged.profdata")
    args = ["llvm-profdata", "merge", f"--input-files={profraw_files}", f"-output={merged_profdata_file}"]
    run_command_with_logging(args)
    os.remove(profraw_files)
    for file_name in file_names:
        os.remove(file_name)
    coverage_binary = simulation_project.get_executable(mode="coverage")
    output_path = os.path.join(project_root, output_dir)
    args = ["llvm-cov", "show", coverage_binary, f"-instr-profile={merged_profdata_file}", "-format=html", f"-output-dir={output_path}"]
    run_command_with_logging(args)
    os.remove(merged_profdata_file)

def open_coverage_report(simulation_project=None, output_dir="coverage", **kwargs):
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    generate_coverage_report(simulation_project=simulation_project, output_dir=output_dir, **kwargs)
    output_path = os.path.join(simulation_project.get_full_path("."), output_dir)
    open_file_with_default_editor(f"{output_path}/index.html")
