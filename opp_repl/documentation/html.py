import logging
import os
import subprocess
import webbrowser

from opp_repl.common import *
from opp_repl.simulation.project import *

_logger = logging.getLogger(__name__)

def generate_html_documentation(simulation_project=None, docker=False, clean_build=False, targets=None):
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    doc_src = simulation_project.get_full_path("doc/src")
    _logger.info("Generating HTML documentation (docker=" + str(docker) + ", " + "clean_build=" + str(clean_build) + ", targets=" + str(targets) + ")")
    if clean_build:
        run_command_with_logging(["rm", "-r", "_build"], cwd=doc_src)
    if docker:
        make_cmd = "./doc-build"
    else:
        make_cmd = "make"
    env = None
    if targets is not None:
        env = os.environ.copy()
        env["DOC_BUILD_TARGET"] = ",".join(targets)
    subprocess.run([make_cmd, "html"], cwd=doc_src, env=env)

def upload_html_documentation(path, simulation_project=None):
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    _logger.info("Uploading HTML documentation, path = " + path)
    run_command_with_logging(["rsync", "-L", "-r", "-e", "ssh -p 2200", ".", "--delete", "--progress", "com@server.omnest.com:" + path], cwd=simulation_project.get_full_path("doc/src/_build/html"))

def open_html_documentation(path="index.html", simulation_project=None):
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    _logger.info("Opening HTML documentation, path = " + path)
    webbrowser.open(simulation_project.get_full_path("doc/src/_build/html/" + path))
