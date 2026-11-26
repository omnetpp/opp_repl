"""
The test map: a tree of text files with the same paths as the project. Each map file tells which
runs used which part of the source file of the same name (see the test selection plan of opp_repl,
``plan/pending/test-selection.md``, section 8.3):

- ``<path>.json`` of a C++ file: ``functions``, for each function body its line range, its name, its
  number of instances (template instantiations), the runs that ran it and the translation units
  that emit it (when they are not only the file itself; more than 20 as the id of a set in
  ``emitter-sets.json``); ``tu_runs`` of a translation unit (the runs
  that ran a function that it emits); ``included_by`` of a header (the translation units that
  include it).
- ``<path>.json`` of a NED file: ``types``, for each declared type the runs that used it (the
  instantiated types and their NED type closure).
- ``<path>.json`` of an ini file: ``sections``, for each section the runs whose section chain has it.
- ``<path>.json`` of another file: ``data``, for each kind (``read``, ``examined``, ``lookup``) the
  runs that used the file so.
- ``<folder>/index.json``: the number of runs that used something below the folder, for each kind,
  and ``listed``, the runs that listed the folder.
- ``runs.json`` (the run table), ``tests.json`` (the test table), ``emitter-sets.json`` (the sets of
  more than 20 translation units that emit a function) and ``header.json``.
- ``release-only.json``: the blocks that only a release build compiles (see
  :py:mod:`opp_repl.test.test_map.ndebug`), with their names, includes and runs (map version 3).

A set of runs is ``"all"``, ``{"except": [run ids]}`` if it holds more than half of the runs, or a
list of run ids. Each map file has one JSON value on each line, so that a git diff shows one function
or one key on each line.
"""

import collections
import datetime
import glob
import gzip
import hashlib
import importlib
import json
import logging
import os
import re
import shutil
import subprocess
import time

from opp_repl.test.test_map.build import get_ned_type_closure

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

TEST_MAP_VERSION = 3

def read_test_map_records(records_folders):
    """Returns the complete records (the ``run.json`` of each run) of the records folders, sorted by run id. A later folder wins for the same run id."""
    records = {}
    for records_folder in records_folders:
        for run_file in glob.glob(os.path.join(records_folder, "*", "run.json")):
            with open(run_file) as f:
                record = json.load(f)
            record["folder"] = os.path.dirname(run_file)
            records[record["id"]] = record
    return [records[run_id] for run_id in sorted(records)]

def is_normal_end(record):
    """
    True if the run ended normally and its record is complete: exit code 0, a profile, and a
    section chain, and no CPU-time or real-time limit stopped it. Where such a limit stops a run
    depends on the machine, so the record does not show what the run of a test uses.
    """
    text = (record.get("end") or {}).get("text") or ""
    return record["exit_code"] == 0 and record["profile"] and record["sections"] is not None and not text.startswith(("CPU time limit reached", "Realtime limit reached"))

def get_fingerprint_ingredients(args):
    """Returns the ingredients of the ``--fingerprint`` argument of a run, for example ``["tplx", "~tNl"]``."""
    for index, arg in enumerate(args):
        value = args[index + 1] if arg == "--fingerprint" and index + 1 < len(args) else arg[len("--fingerprint="):] if arg.startswith("--fingerprint=") else None
        if value is not None:
            return [fingerprint.split("/", 1)[1] for fingerprint in value.split(",") if "/" in fingerprint]
    return []

class RunSets:
    """Writes a set of runs, given as a bit set over the run indices, as ``"all"``, ``{"except": [...]}`` or a list of run ids."""
    def __init__(self, run_ids):
        self.run_ids = run_ids
        self.all = (1 << len(run_ids)) - 1
        # many functions share a set of runs, so each set is converted once
        self.cache = {}

    def ids(self, bits):
        return [self.run_ids[index] for index, bit in enumerate(reversed(bin(bits)[2:])) if bit == "1"]

    def to_json(self, bits):
        result = self.cache.get(bits)
        if result is None:
            if bits == self.all:
                result = "all"
            elif bits.bit_count() > len(self.run_ids) / 2:
                result = {"except": self.ids(self.all & ~bits)}
            else:
                result = self.ids(bits)
            self.cache[bits] = result
        return result

def _bits(indices):
    bits = 0
    for index in indices:
        bits |= 1 << index
    return bits

def _dump_lines(obj):
    # one JSON value on each line, so that a git diff shows one function or one key on each line
    parts = []
    for key, value in obj.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            parts.append(json.dumps(key) + ": [\n" + ",\n".join(json.dumps(item, sort_keys=True) for item in value) + "\n]")
        elif isinstance(value, dict) and value:
            parts.append(json.dumps(key) + ": {\n" + ",\n".join(json.dumps(k) + ": " + json.dumps(v, sort_keys=True) for k, v in sorted(value.items())) + "\n}")
        else:
            parts.append(json.dumps(key) + ": " + json.dumps(value, sort_keys=True))
    return "{\n" + ",\n".join(parts) + "\n}\n"

def _demangle(names):
    plain = [re.split(r"[;:]", name)[-1] if not name.startswith("_Z") else name for name in names]
    try:
        result = subprocess.run(["llvm-cxxfilt"], input="\n".join(plain), capture_output=True, text=True, check=True).stdout.split("\n")
        return dict(zip(names, result))
    except (OSError, subprocess.CalledProcessError) as e:
        _logger.warning(f"Demangling the function names failed, the map has the mangled names: {e}")
        return {name: name for name in names}

def get_test_map_header(simulation_project, mode="coverage"):
    """Returns the header of a map: the project, the map commit and whether the tree had changes, the omnetpp commit, the opp_repl version, the compiler, the feature state and the date."""
    def git(folder, *args):
        result = subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None
    root_folder = simulation_project.get_full_path(".")
    omnetpp_project = simulation_project.get_omnetpp_project()
    # the commit of the opp_repl code that runs, if it is a git checkout, else the version of the package
    opp_repl_folder = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    opp_repl_version = git(opp_repl_folder, "rev-parse", "HEAD")
    if opp_repl_version is None:
        try:
            from opp_repl._version import version as opp_repl_version
        except ImportError:
            pass
    compiler = None
    try:
        cxx = omnetpp_project.get_makefile_inc_config(mode=mode).cxx.split()[-1]
        compiler = subprocess.run([cxx, "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    except Exception as e:
        _logger.debug(f"Cannot find the compiler version: {e}")
    features = None
    feature_state_file = os.path.join(root_folder, ".oppfeaturestate")
    if os.path.exists(feature_state_file):
        with open(feature_state_file) as f:
            features = sorted(re.findall(r'<feature\s+id="([^"]+)"\s+enabled="true"', f.read()))
    return {"version": TEST_MAP_VERSION,
            "project": simulation_project.get_name(),
            "commit": git(root_folder, "rev-parse", "HEAD"),
            "changed_files": bool(git(root_folder, "status", "--porcelain", "--untracked-files=no")),
            "omnetpp_commit": git(omnetpp_project.get_root_path(), "rev-parse", "HEAD") if omnetpp_project.has_root_path() else None,
            "opp_repl_version": opp_repl_version,
            "opp_repl_changed_files": bool(git(opp_repl_folder, "status", "--porcelain", "--untracked-files=no")),
            "compiler": compiler,
            "enabled_features": features,
            "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

def write_test_map(records, build_tables, root_folder, output_folder, header=None, tracked_files=None, release_only_blocks=None):
    """
    Writes the test map of *records* (see :py:func:`read_test_map_records`) and *build_tables* (see
    :py:func:`opp_repl.test.test_map.build.make_test_map_build_tables`) into *output_folder*.
    *root_folder* is the project root of the map commit; *tracked_files* is the set of files that git
    tracks there (from ``git ls-files`` if not given). A file that a run read or examined goes into
    the map only if git tracks it; a failed lookup goes into the map for any path.
    *release_only_blocks* are the blocks of
    :py:func:`opp_repl.test.test_map.ndebug.scan_release_only_blocks`; the map gives each its runs.

    Returns (dict):
        some numbers of the map, for the log.
    """
    start_time = time.time()
    if os.path.exists(output_folder) and os.listdir(output_folder) and not os.path.exists(os.path.join(output_folder, "header.json")):
        raise Exception(f"{output_folder} is not empty and holds no test map (no header.json), so it is not removed")
    if tracked_files is None:
        tracked_files = set(subprocess.run(["git", "-C", root_folder, "ls-files", "-z"], capture_output=True, text=True, check=True).stdout.split("\0"))
    run_ids = [record["id"] for record in records]
    run_sets = RunSets(run_ids)
    use = collections.defaultdict(lambda: collections.defaultdict(int)) # path -> kind -> bits of the runs
    files = collections.defaultdict(dict)
    # the functions that ran
    function_runs = collections.defaultdict(list)
    for index, record in enumerate(records):
        functions_file = os.path.join(record["folder"], "functions.txt.gz")
        if os.path.exists(functions_file):
            with gzip.open(functions_file, "rt") as f:
                for name in f.read().split("\n"):
                    if name:
                        function_runs[name].append(index)
    _logger.info(f"Read the functions of {len(records)} runs ({time.time() - start_time:.1f} s)")
    functions = build_tables["functions"]
    emitters = build_tables["emitters"]
    entries = collections.defaultdict(dict) # file -> (first line, last line) -> entry
    for index, (name, file_name, first_line, last_line) in enumerate(functions):
        entry = entries[file_name].setdefault((first_line, last_line), {"names": [], "bits": 0, "units": set()})
        entry["names"].append(name)
        entry["bits"] |= _bits(function_runs.get(name, []))
        entry["units"].update(emitters.get(str(index), [file_name]))
    demangled = _demangle([entry["names"][0] for file_entries in entries.values() for entry in file_entries.values()])
    tu_bits = collections.defaultdict(int)
    emitter_sets = {}
    for file_name, file_entries in entries.items():
        items = []
        for (first_line, last_line), entry in sorted(file_entries.items()):
            item = {"lines": [first_line, last_line], "name": demangled[entry["names"][0]][:200]}
            if len(entry["names"]) > 1:
                item["instances"] = len(entry["names"])
            if entry["bits"]:
                item["runs"] = run_sets.to_json(entry["bits"])
                for unit in entry["units"]:
                    tu_bits[unit] |= entry["bits"]
                use[file_name]["functions"] |= entry["bits"]
            units = sorted(entry["units"] - {file_name})
            if len(units) > 20:
                set_id = hashlib.sha1("\n".join(units).encode("utf-8")).hexdigest()[:10]
                emitter_sets[set_id] = units
                item["tus"] = {"count": len(units), "set": set_id}
            elif units:
                item["tus"] = units
            items.append(item)
        files[file_name]["functions"] = items
    for unit, bits in tu_bits.items():
        files[unit]["tu_runs"] = run_sets.to_json(bits)
    included_by = collections.defaultdict(list)
    for unit, header_files in build_tables["includes"].items():
        for header_file in header_files:
            included_by[header_file].append(unit)
    for header_file, units in included_by.items():
        files[header_file]["included_by"] = sorted(units)
    # the release-only blocks: the runs of the functions that hold a block, or of the translation
    # units that include the file of a block outside the functions
    release_only = []
    for block in release_only_blocks or []:
        first, last = block["lines"]
        containing = [entry for (first_line, last_line), entry in entries.get(block["path"], {}).items() if first_line <= first and last <= last_line]
        bits = 0
        for entry in containing:
            bits |= entry["bits"]
        if not containing:
            for unit in [block["path"]] if os.path.splitext(block["path"])[1] in (".cc", ".cpp", ".cxx", ".c") else included_by.get(block["path"], []):
                bits |= tu_bits.get(unit, 0)
        release_only.append(dict(block, inside_function=bool(containing), runs=run_sets.to_json(bits)))
    _logger.info(f"Made the function map ({time.time() - start_time:.1f} s)")
    # the NED types
    ned_types = build_tables["ned_types"]
    type_bits = collections.defaultdict(int)
    for index, record in enumerate(records):
        for qname in get_ned_type_closure(record["ned_types"], ned_types):
            type_bits[qname] |= 1 << index
    ned_files = collections.defaultdict(dict)
    unresolved_types = set()
    for qname, bits in type_bits.items():
        if qname in ned_types:
            ned_files[ned_types[qname][0]][qname] = bits
        else:
            unresolved_types.add(qname)
    for file_name, types in ned_files.items():
        files[file_name]["types"] = {qname: run_sets.to_json(bits) for qname, bits in types.items()}
        for bits in types.values():
            use[file_name]["ned"] |= bits
    # the ini sections
    section_bits = collections.defaultdict(lambda: collections.defaultdict(int))
    for index, record in enumerate(records):
        ini_file = os.path.normpath(os.path.join(record["working_directory"], record["ini_file"]))
        for section in record["sections"] or []:
            section_bits[ini_file][section] |= 1 << index
    for file_name, sections in section_bits.items():
        files[file_name]["sections"] = {section: run_sets.to_json(bits) for section, bits in sections.items()}
        for bits in sections.values():
            use[file_name]["ini"] |= bits
    # the other files
    data_bits = collections.defaultdict(lambda: collections.defaultdict(int))
    listed_bits = collections.defaultdict(int)
    for index, record in enumerate(records):
        with open(os.path.join(record["folder"], "files.txt"), errors="surrogateescape") as f:
            for line in f:
                kind, _, path = line.rstrip("\n").partition(" ")
                if kind == "listed":
                    listed_bits[path] |= 1 << index
                elif kind == "lookup" or path in tracked_files:
                    data_bits[path][kind] |= 1 << index
    for file_name, kinds in data_bits.items():
        files[file_name]["data"] = {kind: run_sets.to_json(bits) for kind, bits in kinds.items()}
        for bits in kinds.values():
            use[file_name]["data"] |= bits
    _logger.info(f"Made the NED, ini and data map ({time.time() - start_time:.1f} s)")
    # the folder index
    folder_use = collections.defaultdict(lambda: collections.defaultdict(int))
    for file_name, kinds in use.items():
        parts = file_name.split("/")
        for depth in range(len(parts)):
            folder = "/".join(parts[:depth])
            for kind, bits in kinds.items():
                folder_use[folder][kind] |= bits
    for folder in listed_bits:
        folder_use[folder]
    # write
    if os.path.exists(output_folder):
        shutil.rmtree(output_folder)
    def write(path, obj, lines):
        if os.path.isabs(path) or ".." in path.split("/"):
            raise Exception(f"A path outside the map: {path}")
        full_path = os.path.join(output_folder, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", errors="surrogateescape") as f:
            f.write(_dump_lines(obj) if lines else json.dumps(obj, indent=1, sort_keys=True) + "\n")
    for file_name, obj in files.items():
        write(file_name + ".json", obj, True)
    for folder, kinds in folder_use.items():
        obj = {kind: bits.bit_count() for kind, bits in sorted(kinds.items())}
        if folder in listed_bits:
            obj["listed"] = run_sets.to_json(listed_bits[folder])
        write(os.path.join(folder, "index.json"), obj, False)
    runs = {}
    tests = collections.defaultdict(dict)
    for record in records:
        runs[record["id"]] = {"key": record["key"], "kind": record["kind"], "working_directory": record["working_directory"], "ini_file": record["ini_file"],
                              "config": record["config"], "run_number": record["run_number"], "sim_time_limit": record["sim_time_limit"],
                              "exit_code": record["exit_code"], "end": record["end"], "normal_end": is_normal_end(record), "sections": record["sections"]}
        if record["kind"] == "fingerprint":
            for ingredients in get_fingerprint_ingredients(record["args"]):
                tests["fingerprint"][record["key"] + ":" + ingredients] = [record["id"]]
        else:
            tests[record["kind"]][record["key"]] = [record["id"]]
        if record["kind"] == "smoke":
            # a sanitizer test stops where the smoke test of its config stops, and the sanitizer
            # only examines the code that runs, so the run of the smoke test is its run too
            tests["sanitizer"]["sanitizer" + record["key"][len("smoke"):]] = [record["id"]]
    write("emitter-sets.json", {"sets": emitter_sets}, True)
    write("release-only.json", {"blocks": release_only}, True)
    write("runs.json", runs, True)
    write("tests.json", dict(tests), False)
    header = dict(header or {}, runs=len(records), unresolved_ned_types=sorted(unresolved_types), ned_errors=build_tables.get("ned_errors", []))
    write("header.json", header, False)
    numbers = {"runs": len(records), "map files": len(files), "functions": sum(len(file_entries) for file_entries in entries.values()),
               "functions that ran": sum(1 for file_entries in entries.values() for entry in file_entries.values() if entry["bits"]),
               "NED files": len(ned_files), "ini files": len(section_bits), "data files": len(data_bits), "listed folders": len(listed_bits),
               "time": round(time.time() - start_time, 1)}
    _logger.info(f"Wrote the test map into {output_folder}: {numbers}")
    return numbers

def get_release_only_blocks(simulation_project):
    """Returns the release-only blocks of the C++ files that git tracks in the C++ folders of the project (rule R-NDEBUG)."""
    from opp_repl.test.test_map.ndebug import scan_release_only_blocks
    root_folder = simulation_project.get_full_path(".")
    result = subprocess.run(["git", "-C", root_folder, "ls-files", "-z", "--", *simulation_project.cpp_folders], capture_output=True, text=True, check=True)
    cpp_files = [path for path in result.stdout.split("\0") if os.path.splitext(path)[1] in (".h", ".hpp", ".hxx", ".cc", ".cpp", ".cxx", ".c")]
    blocks = scan_release_only_blocks(root_folder, cpp_files, simulation_project.include_folders)
    _logger.info(f"Found {len(blocks)} release-only blocks in {len(cpp_files)} C++ files")
    return blocks

def get_default_test_map_folder(simulation_project, name):
    """Returns the default folder of the test map (*name* ``map``) or of its records (*name* ``records``): ``coverage/test-map/<name>`` in the project root."""
    return simulation_project.get_full_path(os.path.join("coverage", "test-map", name))

def clear_test_map_records(records_folder):
    """Removes the records of a records folder: the folders that hold a record and the file trace library. Refuses a folder that holds anything else."""
    if not os.path.exists(records_folder):
        return
    names = os.listdir(records_folder)
    for name in names:
        path = os.path.join(records_folder, name)
        is_record = os.path.isdir(path) and re.fullmatch(r"[0-9a-f]{10}", name) and set(os.listdir(path)) <= {"run.json", "functions.txt.gz", "files.txt", "profraw"} | {f for f in os.listdir(path) if f.startswith("trace.")}
        is_library = name.startswith("libopp_repl_filetrace.so") or name == "build-tables.json.gz"
        if not (is_record or is_library):
            raise Exception(f"{records_folder} holds {name}, which is not a record of the test map, so the folder is not cleared")
    for name in names:
        path = os.path.join(records_folder, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

# the run command of each kind of test that the map can hold: (module, function)
TEST_MAP_RUN_FUNCTIONS = {
    "fingerprint": ("opp_repl.test.fingerprint.task", "run_fingerprint_tests"),
    "statistical": ("opp_repl.test.statistical", "run_statistical_tests"),
    "smoke": ("opp_repl.test.smoke", "run_smoke_tests"),
}

def get_test_map_run_function(kind):
    """Returns the run command of the tests of *kind*, which takes the option ``test_map_records``."""
    if kind not in TEST_MAP_RUN_FUNCTIONS:
        raise Exception(f"The test map does not hold the {kind} tests; it holds {', '.join(TEST_MAP_RUN_FUNCTIONS)}")
    module_name, function_name = TEST_MAP_RUN_FUNCTIONS[kind]
    return getattr(importlib.import_module(module_name), function_name)

def update_test_map(simulation_project=None, records_folders=None, output_folder=None, build_tables_file=None, run=True, kinds=None, **kwargs):
    """
    Makes the test map: runs the tests of each kind in coverage mode with records (unless *run* is
    false), makes the build tables of the coverage build (unless *build_tables_file* gives them),
    and writes the map.

    Parameters:
        records_folders (list of strings or None):
            The records folders. A run writes its records into the first one, after it removes the
            records that it holds. Default: ``coverage/test-map/records`` in the project root.

        output_folder (string or None):
            The folder of the map. Default: ``coverage/test-map/map`` in the project root.

        build_tables_file (string or None):
            A file of :py:func:`opp_repl.test.test_map.build.write_test_map_build_tables`. If it is
            not given, the build tables come from the coverage build and the profiles of the pool,
            and they are written to ``build-tables.json.gz`` in the first records folder.

        run (bool):
            If false, the map comes from the records that the folders already hold.

        kinds (list of strings or None):
            The kinds of test that run, one after the other, for example ``["fingerprint",
            "statistical"]`` (see :py:data:`TEST_MAP_RUN_FUNCTIONS`). Default: ``["fingerprint"]``.

        kwargs (dict):
            The parameters of the run command of each kind, for example
            :py:func:`opp_repl.test.fingerprint.task.run_fingerprint_tests`, and its filters.

    Returns (:py:class:`MultipleTestTaskResults <opp_repl.test.task.MultipleTestTaskResults>` or None):
        the results of the tests (for more than one kind, a list of the results of each kind), or
        None if *run* is false.
    """
    from opp_repl.simulation.project import get_default_simulation_project
    from opp_repl.test.coverage import merge_coverage_profiles
    from opp_repl.test.task import MultipleTestTaskResults
    from opp_repl.test.test_map.build import make_test_map_build_tables, read_test_map_build_tables, write_test_map_build_tables
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    records_folders = [os.path.abspath(folder) for folder in (records_folders or [get_default_test_map_folder(simulation_project, "records")])]
    output_folder = os.path.abspath(output_folder or get_default_test_map_folder(simulation_project, "map"))
    mode = "coverage"
    kinds = kinds or ["fingerprint"]
    run_functions = [get_test_map_run_function(kind) for kind in kinds]
    result = None
    if run:
        clear_test_map_records(records_folders[0])
        results = [run_function(simulation_project=simulation_project, test_map_records=records_folders[0], **dict(kwargs, mode=mode)) for run_function in run_functions]
        result = results[0] if len(results) == 1 else MultipleTestTaskResults(results=results)
    if build_tables_file:
        build_tables = read_test_map_build_tables(build_tables_file)
    else:
        build_tables = make_test_map_build_tables(simulation_project, merge_coverage_profiles(simulation_project, mode=mode), mode=mode)
        write_test_map_build_tables(build_tables, os.path.join(records_folders[0], "build-tables.json.gz"))
    records = read_test_map_records(records_folders)
    if not records:
        raise Exception(f"No records of the test map in {', '.join(records_folders)}")
    write_test_map(records, build_tables, simulation_project.get_full_path("."), output_folder, header=get_test_map_header(simulation_project, mode=mode),
                   release_only_blocks=get_release_only_blocks(simulation_project))
    return result
