import fnmatch
import glob
import json
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

_METRICS = ["lines", "functions", "branches"]

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

def _add_count(counts, key, count):
    # None is a branch whose block never ran (lcov "-"); it stays None until a run reaches the block
    previous = counts.get(key)
    counts[key] = count if previous is None else previous + (count or 0)

def read_lcov_files(lcov_files):
    """
    Reads lcov files into ``{test name: {source file: record}}``. A record maps ``lines``, ``functions``
    and ``branches`` to execution counts, and ``function_lines`` to the first line of each function.
    The counts of the same item in several files add up. A record without a test name has the name "".
    """
    tests = {}
    for lcov_file in lcov_files:
        test_name = ""
        record = None
        with open(lcov_file) as f:
            for line in f:
                key, _, value = line.rstrip("\n").partition(":")
                if key == "TN":
                    test_name = value
                elif key == "SF":
                    records = tests.setdefault(test_name, {})
                    record = records.setdefault(value, {"lines": {}, "functions": {}, "function_lines": {}, "branches": {}})
                elif key == "DA":
                    number, count = value.split(",")[:2]
                    _add_count(record["lines"], int(number), int(count))
                elif key == "FN":
                    # FN:<line>,<name> from llvm-cov, FN:<line>,<end line>,<name> from lcov 2
                    parts = value.split(",")
                    name = ",".join(parts[2:]) if len(parts) > 2 and parts[1].isdigit() else ",".join(parts[1:])
                    record["function_lines"][name] = int(parts[0])
                    _add_count(record["functions"], name, 0)
                elif key == "FNDA":
                    count, name = value.split(",", 1)
                    _add_count(record["functions"], name, int(count))
                elif key == "BRDA":
                    number, block, branch, taken = value.split(",")
                    _add_count(record["branches"], (int(number), block, branch), None if taken == "-" else int(taken))
                elif key == "end_of_record":
                    record = None
    return tests

def merge_lcov_tests(tests):
    """Adds the records of all tests into one ``{source file: record}``."""
    merged = {}
    for records in tests.values():
        for source, record in records.items():
            merged_record = merged.setdefault(source, {"lines": {}, "functions": {}, "function_lines": {}, "branches": {}})
            for kind in ["lines", "functions", "branches"]:
                for key, count in record[kind].items():
                    _add_count(merged_record[kind], key, count)
            merged_record["function_lines"].update(record["function_lines"])
    return merged

def count_coverage(records):
    """Returns the number of items that ran (``hit``) and of all items (``found``) of each metric in *records*."""
    result = {metric: {"hit": 0, "found": 0} for metric in _METRICS}
    for record in records:
        for metric in _METRICS:
            counts = record[metric].values()
            result[metric]["hit"] += sum(1 for count in counts if count)
            result[metric]["found"] += len(counts)
    return result

def get_coverage_area(source, area_pattern):
    """Returns the folder of *source* that matches *area_pattern* (for example ``src/inet/*``), or "other"."""
    if area_pattern:
        depth = len(area_pattern.split("/"))
        parts = source.split("/")
        if len(parts) > depth and fnmatch.fnmatch("/".join(parts[:depth]), area_pattern):
            return "/".join(parts[:depth])
    return "other"

def get_coverage_percent(counts):
    return 100 * counts["hit"] / counts["found"] if counts["found"] else None

def summarize_coverage(tests, area_pattern=None):
    """
    Returns the coverage summary of *tests* (see :py:func:`read_lcov_files`): the ``totals``, the totals
    of each area (``areas``), of each test (``suites``) and of each source file (``files``).
    """
    merged = merge_lcov_tests(tests)
    area_records = {}
    for source, record in merged.items():
        area_records.setdefault(get_coverage_area(source, area_pattern), []).append(record)
    return {"totals": count_coverage(merged.values()),
            "areas": {area: count_coverage(records) for area, records in sorted(area_records.items())},
            "suites": {test_name: count_coverage(records.values()) for test_name, records in sorted(tests.items())},
            "files": {source: count_coverage([record]) for source, record in sorted(merged.items())}}

def get_coverage_change(summary, previous):
    """Returns the change of the coverage percent of each metric against *previous*, in percentage points."""
    change = {}
    for metric in _METRICS:
        percent = get_coverage_percent(summary["totals"][metric])
        previous_percent = get_coverage_percent(previous["totals"][metric]) if metric in previous.get("totals", {}) else None
        change[metric] = None if percent is None or previous_percent is None else round(percent - previous_percent, 4)
    return change

def write_lcov_file(merged, file_name):
    """Writes *merged* (see :py:func:`merge_lcov_tests`) as an lcov file."""
    with open(file_name, "w") as f:
        for source, record in sorted(merged.items()):
            f.write(f"SF:{source}\n")
            for name, line in sorted(record["function_lines"].items(), key=lambda item: (item[1], item[0])):
                f.write(f"FN:{line},{name}\n")
            for name, count in sorted(record["functions"].items()):
                f.write(f"FNDA:{count},{name}\n")
            f.write(f"FNF:{len(record['functions'])}\nFNH:{sum(1 for count in record['functions'].values() if count)}\n")
            for (line, block, branch), count in sorted(record["branches"].items()):
                f.write(f"BRDA:{line},{block},{branch},{'-' if count is None else count}\n")
            f.write(f"BRF:{len(record['branches'])}\nBRH:{sum(1 for count in record['branches'].values() if count)}\n")
            for line, count in sorted(record["lines"].items()):
                f.write(f"DA:{line},{count}\n")
            f.write(f"LF:{len(record['lines'])}\nLH:{sum(1 for count in record['lines'].values() if count)}\n")
            f.write("end_of_record\n")

def _format_percent(counts):
    percent = get_coverage_percent(counts)
    return "-" if percent is None else f"{percent:.2f}%"

def _format_change(value):
    return "" if value is None else f"{value:+.2f}"

def format_coverage_markdown(summary, previous=None):
    """Returns the coverage summary as Markdown, with the change against *previous* if given."""
    lines = ["## Coverage", ""]
    if summary.get("commit"):
        lines += [f"Commit `{summary['commit']}`" + (f", {summary['date']}" if summary.get("date") else "") + ".", ""]
    if previous and previous.get("commit"):
        lines += [f"Change against `{previous['commit']}`, in percentage points.", ""]
    change = get_coverage_change(summary, previous) if previous else {}
    lines += ["| Metric | Covered | Total | Coverage | Change |", "| --- | ---: | ---: | ---: | ---: |"]
    for metric in _METRICS:
        counts = summary["totals"][metric]
        lines.append(f"| {metric} | {counts['hit']} | {counts['found']} | {_format_percent(counts)} | {_format_change(change.get(metric))} |")
    for title, key in [("Suites", "suites"), ("Areas", "areas")]:
        lines += ["", f"### {title}", "", "| Name | Lines | Change | Functions | Branches |", "| --- | ---: | ---: | ---: | ---: |"]
        for name, counts in summary[key].items():
            previous_counts = previous.get(key, {}).get(name) if previous else None
            line_change = get_coverage_change({"totals": counts}, {"totals": previous_counts})["lines"] if previous_counts else None
            lines.append(f"| {name or '(no name)'} | {_format_percent(counts['lines'])} | {_format_change(line_change)} | {_format_percent(counts['functions'])} | {_format_percent(counts['branches'])} |")
    return "\n".join(lines) + "\n"

def read_coverage_summary(file_name):
    """Reads a summary written by :py:func:`coverage_report`: a ``summary.json``, or the last line of a history file."""
    with open(file_name) as f:
        text = f.read()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads([line for line in text.splitlines() if line.strip()][-1])

def coverage_report(lcov_files, output_folder=".", previous_file=None, html=False, simulation_project=None, commit=None, date=None):
    """
    Merges lcov files, for example the exports of several test suites or slices, and writes the report
    into *output_folder*: ``coverage.lcov`` (the merged counts), ``summary.json`` (the totals, the areas,
    the suites and the files), ``history.json`` (the summary without the files, on one line, to append to
    a history file), ``summary.md`` and, if *html* is true, the HTML of ``genhtml`` in ``html/``.

    Parameters:
        previous_file (string or None):
            An earlier ``summary.json`` or history file. The summary gives the change against it.

        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>` or None):
            Gives the ``areas`` pattern of the ``report`` aspect of its ``coverage`` test parameters, and
            the root folder in which ``genhtml`` finds the sources.

        commit, date (string or None):
            Recorded in the summary.

    Returns (dict):
        the summary.
    """
    tests = read_lcov_files(lcov_files)
    area_pattern = simulation_project.test_parameters.get("coverage", {}).get("report", {}).get("areas") if simulation_project else None
    summary = {"commit": commit, "date": date, **summarize_coverage(tests, area_pattern)}
    previous = read_coverage_summary(previous_file) if previous_file else None
    summary["change"] = get_coverage_change(summary, previous) if previous else None
    os.makedirs(output_folder, exist_ok=True)
    lcov_file = os.path.abspath(os.path.join(output_folder, "coverage.lcov"))
    write_lcov_file(merge_lcov_tests(tests), lcov_file)
    with open(os.path.join(output_folder, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1, sort_keys=True)
    with open(os.path.join(output_folder, "history.json"), "w") as f:
        f.write(json.dumps({key: value for key, value in summary.items() if key != "files"}, sort_keys=True) + "\n")
    with open(os.path.join(output_folder, "summary.md"), "w") as f:
        f.write(format_coverage_markdown(summary, previous))
    if html:
        root_folder = simulation_project.get_full_path(".") if simulation_project else os.getcwd()
        title = simulation_project.get_name() if simulation_project else "coverage"
        # --quiet: without it, genhtml prints a block for each source file (thousands of lines for INET)
        args = ["genhtml", lcov_file, f"--output-directory={os.path.abspath(os.path.join(output_folder, 'html'))}", "--branch-coverage", "--demangle-cpp", "--quiet", f"--title={title}"]
        run_command_with_logging(args, cwd=root_folder, error_message="Generating the HTML coverage report failed", command_line_logger=_logger)
    return summary
