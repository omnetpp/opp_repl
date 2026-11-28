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
from opp_repl.test.test_map.record import get_test_map_run_id

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
    True if the run ended normally and its record is complete: exit code 0, a profile, a section
    chain, the NED types, and no CPU-time or real-time limit stopped it. Where such a limit stops a
    run depends on the machine, so the record does not show what the run of a test uses.

    A run of an interactive config stops with an error at its prompt for user input, and the tests
    skip it. It stops at the same point each time, so its profile and its NED types show all that it
    used, and it ends normally too. A change that gives the asked parameter a value changes the ini
    file or a NED type of the run, which the rules see.
    """
    text = (record.get("end") or {}).get("text") or ""
    return (record["exit_code"] == 0 or bool(record.get("interactive"))) and record["profile"] and record["sections"] is not None \
        and record.get("ned_types") is not None and not text.startswith(("CPU time limit reached", "Realtime limit reached"))

def get_fingerprint_ingredients(args):
    """Returns the ingredients of the ``--fingerprint`` argument of a run, for example ``["tplx", "~tNl"]``."""
    for index, arg in enumerate(args):
        value = args[index + 1] if arg == "--fingerprint" and index + 1 < len(args) else arg[len("--fingerprint="):] if arg.startswith("--fingerprint=") else None
        if value is not None:
            return [fingerprint.split("/", 1)[1] for fingerprint in value.split(",") if "/" in fingerprint]
    return []

def _get_record_functions(record):
    # the functions that the run ran: in memory for a run of an old map, else in functions.txt.gz of its folder
    if "functions" in record:
        return record["functions"]
    functions_file = os.path.join(record["folder"], "functions.txt.gz")
    if not os.path.exists(functions_file):
        return []
    with gzip.open(functions_file, "rt") as f:
        return [name for name in f.read().split("\n") if name]

def _get_record_files(record):
    # the (kind, path) pairs of the files that the run used: in memory for a run of an old map, else in files.txt of its folder
    if "files" in record:
        return record["files"]
    with open(os.path.join(record["folder"], "files.txt"), errors="surrogateescape") as f:
        return [tuple(line.rstrip("\n").partition(" ")[::2]) for line in f]

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

# the Python packages that draw the charts of the chart tests: another version can draw another image
CHART_PYTHON_PACKAGES = ["matplotlib", "numpy", "pandas", "scipy"]

def get_chart_python_packages():
    """Returns the versions of :py:data:`CHART_PYTHON_PACKAGES` that this Python has, None for a package that it does not have."""
    import importlib.metadata
    versions = {}
    for name in CHART_PYTHON_PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions

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
    opp_repl_commit = opp_repl_version
    if opp_repl_version is None:
        try:
            from opp_repl._version import version as opp_repl_version
            # an installed package has no git checkout; setuptools_scm writes its commit as "g<hash>"
            from opp_repl._version import commit_id
            opp_repl_commit = commit_id[1:] if commit_id and commit_id.startswith("g") else commit_id
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
            # the commit that a pull request job installs to test in the environment of the map (D9)
            "opp_repl_commit": opp_repl_commit,
            "opp_repl_changed_files": bool(git(opp_repl_folder, "status", "--porcelain", "--untracked-files=no")),
            "compiler": compiler,
            "enabled_features": features,
            "python_packages": get_chart_python_packages(),
            "date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

def read_test_map_members(records_folders):
    """
    Returns the members of the tests of the kinds whose test is not one run, from the files
    ``<kind>-tests.json`` of the records folders: ``{kind: {test key: [run keys]}}``. A chart test
    reads the results of the simulations of the folder of its ``.anf`` file.
    """
    members = collections.defaultdict(dict)
    for records_folder in records_folders:
        for members_file in glob.glob(os.path.join(records_folder, "*-tests.json")):
            with open(members_file) as f:
                members[os.path.basename(members_file)[:-len("-tests.json")]].update(json.load(f))
    return dict(members)

# the files of a map that describe the map and not a file of the project
TEST_MAP_TOP_LEVEL_FILES = ["header.json", "runs.json", "tests.json", "emitter-sets.json", "release-only.json"]

def read_test_map_runs(map_folder, build_tables):
    """
    Returns the data of each run of the map in *map_folder* as records for :py:func:`write_test_map`,
    sorted by run id, and the members of the kinds whose test is not one run (as
    :py:func:`read_test_map_members` gives them). *build_tables* are the build tables of the map
    commit: the map gives only the line range of a function that a run ran, and the function table
    gives the names of the functions of each line range.

    A record holds the functions, the files, the listed folders, the NED types (with their closure),
    the section chain, the headers that the own code of a test includes, and the entry of the run in
    ``runs.json``. The writer, with these records and the same build tables, writes the same map
    (section 15.6 of the test selection plan), except the NED types of the header that are not in the
    NED type table: the map does not tell which run used them.
    """
    def read(path):
        with open(os.path.join(map_folder, path), errors="surrogateescape") as f:
            return json.load(f)
    header = read("header.json")
    runs = read("runs.json")
    tests = read("tests.json")
    run_ids = sorted(runs)
    def decode(value):
        if value == "all":
            return run_ids
        if isinstance(value, dict):
            excluded = set(value["except"])
            return [run_id for run_id in run_ids if run_id not in excluded]
        return value
    names = collections.defaultdict(list)
    for name, file_name, first_line, last_line in build_tables["functions"]:
        names[(file_name, first_line, last_line)].append(name)
    data = {run_id: {"functions": set(), "files": set(), "ned_types": set(), "includes": set()} for run_id in run_ids}
    for folder, _, file_names in os.walk(map_folder):
        relative_folder = os.path.relpath(folder, map_folder)
        relative_folder = "" if relative_folder == "." else relative_folder
        for file_name in file_names:
            if not file_name.endswith(".json") or (not relative_folder and file_name in TEST_MAP_TOP_LEVEL_FILES):
                continue
            obj = read(os.path.join(relative_folder, file_name))
            if file_name == "index.json":
                for run_id in decode(obj.get("listed", [])):
                    data[run_id]["files"].add(("listed", relative_folder))
                continue
            path = os.path.join(relative_folder, file_name[:-len(".json")])
            for item in obj.get("functions", []):
                if "runs" in item:
                    function_names = names.get((path, *item["lines"]))
                    if not function_names:
                        raise Exception(f"The build tables have no function at {path}:{item['lines'][0]}-{item['lines'][1]}, so they are not the build tables of the map {map_folder}")
                    for run_id in decode(item["runs"]):
                        data[run_id]["functions"].update(function_names)
            for kind, value in obj.get("data", {}).items():
                for run_id in decode(value):
                    data[run_id]["files"].add((kind, path))
            for qname, value in obj.get("types", {}).items():
                for run_id in decode(value):
                    data[run_id]["ned_types"].add(qname)
            for run_id in decode(obj.get("test_runs", [])):
                data[run_id]["includes"].add(path)
    ingredients = collections.defaultdict(list)
    for key, test_run_ids in tests.get("fingerprint", {}).items():
        for run_id in test_run_ids:
            if key.startswith(runs[run_id]["key"] + ":"):
                ingredients[run_id].append(key[len(runs[run_id]["key"]) + 1:])
    records = []
    for run_id in run_ids:
        run = runs[run_id]
        record = {name: run[name] for name in ("key", "kind", "working_directory", "ini_file", "config", "run_number", "sim_time_limit", "exit_code", "end", "sections")}
        record.update(id=run_id, commit=run.get("commit") or header.get("commit"),
                      # is_normal_end() of the record gives the value of the map
                      profile=run["normal_end"], functions=sorted(data[run_id]["functions"]), files=sorted(data[run_id]["files"]),
                      ned_types=sorted(data[run_id]["ned_types"]), includes=sorted(data[run_id]["includes"]))
        if run["kind"] == "fingerprint":
            record["ingredients"] = ingredients[run_id]
        records.append(record)
    # a kind whose test keys are not the keys of their runs (the chart tests) has members
    members = {}
    for kind, kind_tests in tests.items():
        if kind in ("fingerprint", "sanitizer"):
            continue
        if any(len(test_run_ids) != 1 or runs[test_run_ids[0]]["key"] != key for key, test_run_ids in kind_tests.items()):
            members[kind] = {key: [runs[run_id]["key"] for run_id in test_run_ids] for key, test_run_ids in kind_tests.items()}
    return records, members

def write_test_map(records, build_tables, root_folder, output_folder, header=None, tracked_files=None, release_only_blocks=None, members=None):
    """
    Writes the test map of *records* (see :py:func:`read_test_map_records`) and *build_tables* (see
    :py:func:`opp_repl.test.test_map.build.make_test_map_build_tables`) into *output_folder*.
    *root_folder* is the project root of the map commit; *tracked_files* is the set of files that git
    tracks there (from ``git ls-files`` if not given). A file that a run read or examined goes into
    the map only if git tracks it; a failed lookup goes into the map for any path.
    *release_only_blocks* are the blocks of
    :py:func:`opp_repl.test.test_map.ndebug.scan_release_only_blocks`; the map gives each its runs.
    *members* are the tests of :py:func:`read_test_map_members`: the runs of such a kind are not
    tests themselves.

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
        for name in _get_record_functions(record):
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
    # the headers that the own code of a test includes (an opp test or a binary test): the
    # translation units of the test are not in the build tables of the project (rule R4)
    test_include_bits = collections.defaultdict(int)
    for index, record in enumerate(records):
        for header_file in record.get("includes") or []:
            test_include_bits[header_file] |= 1 << index
    for header_file, bits in test_include_bits.items():
        files[header_file]["test_runs"] = run_sets.to_json(bits)
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
        for qname in get_ned_type_closure(record["ned_types"] or [], ned_types):
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
        if not record["ini_file"]:
            continue
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
        for kind, path in _get_record_files(record):
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
                              "exit_code": record["exit_code"], "end": record["end"], "normal_end": is_normal_end(record), "sections": record["sections"],
                              # the commit of the record: an updated map keeps the runs of the old map (15.6 of the plan)
                              "commit": record.get("commit") or (header or {}).get("commit")}
        if record["kind"] == "fingerprint":
            for ingredients in record["ingredients"] if "ingredients" in record else get_fingerprint_ingredients(record["args"]):
                tests["fingerprint"][record["key"] + ":" + ingredients] = [record["id"]]
        elif record["kind"] not in (members or {}):
            tests[record["kind"]][record["key"]] = [record["id"]]
        if record["kind"] == "smoke":
            # a sanitizer test stops where the smoke test of its config stops, and the sanitizer
            # only examines the code that runs, so the run of the smoke test is its run too
            tests["sanitizer"]["sanitizer" + record["key"][len("smoke"):]] = [record["id"]]
    run_id_set = set(run_ids)
    for kind, kind_members in (members or {}).items():
        for test_key, run_keys in kind_members.items():
            tests[kind][test_key] = sorted(run_id for run_id in map(get_test_map_run_id, run_keys) if run_id in run_id_set)
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
        is_library = name.startswith("libopp_repl_filetrace.so") or name == "build-tables.json.gz" or name.endswith("-tests.json")
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
    "unit": ("opp_repl.test.opp", "run_unit_tests"),
    "module": ("opp_repl.test.opp", "run_module_tests"),
    "queueing": ("opp_repl.test.opp", "run_queueing_tests"),
    "protocol": ("opp_repl.test.opp", "run_protocol_tests"),
    "packet": ("opp_repl.test.opp", "run_packet_tests"),
    "chart": ("opp_repl.test.chart", "run_chart_tests"),
}

def get_test_map_run_function(kind):
    """Returns the run command of the tests of *kind*, which takes the option ``test_map_records``."""
    if kind not in TEST_MAP_RUN_FUNCTIONS:
        raise Exception(f"The test map does not hold the {kind} tests; it holds {', '.join(TEST_MAP_RUN_FUNCTIONS)}")
    module_name, function_name = TEST_MAP_RUN_FUNCTIONS[kind]
    return getattr(importlib.import_module(module_name), function_name)

# the file of the build tables in a map: an update of the map needs them (section 15.6 of the plan)
TEST_MAP_BUILD_TABLES_FILE = "build-tables.json.gz"

def _get_entries_of_functions(build_tables):
    # the line range (file, first line, last line) of each function name of the function table
    return {name: (file_name, first_line, last_line) for name, file_name, first_line, last_line in build_tables["functions"]}

def _get_run_data(record, tracked_files, build_tables, old_entries):
    # the data of a run that check V5 compares: the function bodies of the old function table that
    # it ran (and the names that the old table does not have), the files as the map holds them, the
    # NED types of the NED type table, the section chain, the includes and the end
    new_names = {name for name, _, _, _ in build_tables["functions"]}
    functions = set()
    unknown = set()
    for name in _get_record_functions(record):
        if name in old_entries:
            functions.add(old_entries[name])
        elif name in new_names:
            unknown.add(name)
    files = {(kind, path) for kind, path in _get_record_files(record) if kind in ("listed", "lookup") or (kind and path in tracked_files)}
    ned_types = {qname for qname in get_ned_type_closure(record["ned_types"] or [], build_tables["ned_types"]) if qname in build_tables["ned_types"]}
    return {"functions": functions, "functions that the old map does not have": unknown, "files": files, "NED types": ned_types,
            "sections": record["sections"], "includes": set(record.get("includes") or []), "end": (record["exit_code"], record["end"])}

def _compare_run_data(new, old):
    # the differences of two results of _get_run_data, as text
    differences = []
    for name, new_value in new.items():
        old_value = old.get(name, set() if isinstance(new_value, set) else None)
        if isinstance(new_value, set):
            for label, values in (("also", new_value - old_value), ("no longer", old_value - new_value)):
                if values:
                    examples = ", ".join(":".join(map(str, value)) if isinstance(value, tuple) else str(value) for value in sorted(values)[:3])
                    differences.append(f"{name}: {label} {len(values)}, for example {examples}")
        elif new_value != old_value:
            differences.append(f"{name}: {new_value} instead of {old_value}")
    return differences

def get_updated_test_map_records(simulation_project, old_map_folder, records, members, build_tables, tracked_files=None):
    """
    Returns the records and the members of the map that updates the map in *old_map_folder* with the
    new *records* and *members* of the build tables *build_tables* (section 15.6 of the test selection
    plan). The selection of the changes from the old map commit to ``HEAD``, with the old map, decides:

    - a run with a new record gets the new record;
    - another run of the old map that the selection does not give, and whose test is a test at
      ``HEAD``, keeps the data of the old map (:py:func:`read_test_map_runs`), if each function body
      that it ran keeps a name in the new function table;
    - the map has no other run, so the selection always gives its tests.

    Returns (tuple):
        the records, the members, the fields of the header (``update_of``, ``full_commit`` and
        ``updates``; a map without old runs is a full map), and the differences of check V5: for each
        new record of a run that the selection does not give, how its data differ from the old map.
    """
    from opp_repl.test.test_map.build import read_test_map_build_tables
    from opp_repl.test.test_map.select import TestMap, select_tests
    root_folder = simulation_project.get_full_path(".")
    if tracked_files is None:
        tracked_files = set(subprocess.run(["git", "-C", root_folder, "ls-files", "-z"], capture_output=True, text=True, check=True).stdout.split("\0"))
    old_build_tables_file = os.path.join(old_map_folder, TEST_MAP_BUILD_TABLES_FILE)
    if not os.path.exists(old_build_tables_file):
        raise Exception(f"The map {old_map_folder} has no {TEST_MAP_BUILD_TABLES_FILE}, so it cannot be updated; make a full map")
    old_map = TestMap(old_map_folder)
    old_header = old_map.header
    if old_header.get("version") != TEST_MAP_VERSION:
        raise Exception(f"The map {old_map_folder} has version {old_header.get('version')}, so it cannot be updated to version {TEST_MAP_VERSION}; make a full map")
    old_commit = old_header.get("commit")
    if old_header.get("changed_files") or not old_commit:
        raise Exception(f"The map {old_map_folder} does not describe a commit, so it cannot be updated; make a full map")
    old_build_tables = read_test_map_build_tables(old_build_tables_file)
    if subprocess.run(["git", "-C", root_folder, "merge-base", "--is-ancestor", old_commit, "HEAD"], capture_output=True).returncode != 0:
        raise Exception(f"The commit {old_commit[:10]} of the map {old_map_folder} is not an ancestor of HEAD, so the map cannot be updated")
    selection = select_tests(simulation_project=simulation_project, changes=f"{old_commit}..HEAD", map_folder=old_map_folder)
    selected = set()
    for kind, kind_selection in selection.kinds.items():
        kind_tests = old_map.tests.get(kind, {})
        keys = kind_tests if kind_selection.everything else kind_selection.selected
        for key in keys:
            selected.update(kind_tests.get(key, []))
    universe = {kind: set(kind_selection.tests) for kind, kind_selection in selection.kinds.items() if kind_selection.tests is not None}
    old_records, old_members = read_test_map_runs(old_map_folder, old_build_tables)
    old_entries = _get_entries_of_functions(old_build_tables)
    new_names = {name for name, _, _, _ in build_tables["functions"]}
    names_of_entries = collections.defaultdict(list)
    for name, entry in old_entries.items():
        names_of_entries[entry].append(name)
    new_ids = {record["id"] for record in records}
    old_by_id = {record["id"]: record for record in old_records}
    kept = []
    counts = collections.Counter()
    for old_record in old_records:
        run_id = old_record["id"]
        if run_id in new_ids:
            counts["new"] += 1
        elif run_id in selected:
            counts["selected without a new record"] += 1
        elif any(kind in universe and not any(key in universe[kind] for key in keys) for kind, keys in _group_tests(old_map.run_tests.get(old_map.run_index[run_id], [])).items()):
            counts["not a test at HEAD"] += 1
        elif not all(any(name in new_names for name in names_of_entries[entry]) for entry in {old_entries[name] for name in old_record["functions"]}):
            counts["a function without a name in the new build tables"] += 1
        else:
            kept.append(old_record)
    _logger.info(f"The update of the map of {old_commit[:10]} keeps {len(kept)} runs of {len(old_records)}; the others: {dict(counts)}")
    differences = {}
    for record in records:
        if record["id"] in old_by_id and record["id"] not in selected:
            new_data = _get_run_data(record, tracked_files, build_tables, old_entries)
            old_record = old_by_id[record["id"]]
            old_data = {"functions": {old_entries[name] for name in old_record["functions"]}, "functions that the old map does not have": set(),
                        "files": set(old_record["files"]), "NED types": {qname for qname in old_record["ned_types"] if qname in build_tables["ned_types"]},
                        "sections": old_record["sections"], "includes": set(old_record["includes"]), "end": (old_record["exit_code"], old_record["end"])}
            run_differences = _compare_run_data(new_data, old_data)
            if run_differences:
                differences[record["key"]] = run_differences
    result_ids = new_ids | {record["id"] for record in kept}
    result_members = {}
    for kind, kind_members in old_members.items():
        # a test keeps its old members only if the map has all of its runs
        result_members[kind] = {key: run_keys for key, run_keys in kind_members.items() if all(get_test_map_run_id(run_key) in result_ids for run_key in run_keys)}
    for kind, kind_members in (members or {}).items():
        result_members.setdefault(kind, {}).update(kind_members)
    if kept:
        header = {"update_of": old_commit, "full_commit": old_header.get("full_commit") or old_commit, "updates": (old_header.get("updates") or 0) + 1}
    else:
        header = {"updates": 0}
    return sorted(records + kept, key=lambda record: record["id"]), result_members, header, differences

def _group_tests(run_tests):
    # the test keys of a run for each kind
    result = collections.defaultdict(list)
    for kind, key in run_tests:
        result[kind].append(key)
    return result

def update_test_map(simulation_project=None, records_folders=None, output_folder=None, build_tables_file=None, run=True, kinds=None, update_from=None, sample=None, **kwargs):
    """
    Makes the test map: runs the tests of each kind in coverage mode with records (unless *run* is
    false), makes the build tables of the coverage build (unless *build_tables_file* gives them),
    and writes the map. The map holds its build tables (``build-tables.json.gz``).

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

        update_from (string or None):
            The folder of an old map, which can be *output_folder*. The run runs only the tests that
            the selection of the changes from the old map commit to ``HEAD`` gives, and the map keeps
            the data of the old map for the other runs (see :py:func:`get_updated_test_map_records`).
            The command fails after it writes the map if the new record of a run that the selection
            does not give differs from the old map (check V5).

        sample (float or None):
            With *update_from*: the part of the tests that the selection does not give that also run,
            chosen at random, for check V5.

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
        if update_from:
            with open(os.path.join(update_from, "header.json")) as f:
                kwargs = dict(kwargs, changes=f"{json.load(f)['commit']}..HEAD", test_map=os.path.abspath(update_from), **({"sample": sample} if sample else {}))
        results = [run_function(simulation_project=simulation_project, test_map_records=records_folders[0], **dict(kwargs, mode=mode)) for run_function in run_functions]
        result = results[0] if len(results) == 1 else MultipleTestTaskResults(results=results)
    if build_tables_file:
        build_tables = read_test_map_build_tables(build_tables_file)
    else:
        build_tables = make_test_map_build_tables(simulation_project, merge_coverage_profiles(simulation_project, mode=mode), mode=mode)
        write_test_map_build_tables(build_tables, os.path.join(records_folders[0], TEST_MAP_BUILD_TABLES_FILE))
    records = read_test_map_records(records_folders)
    members = read_test_map_members(records_folders)
    header = get_test_map_header(simulation_project, mode=mode)
    differences = {}
    if update_from:
        records, members, header_fields, differences = get_updated_test_map_records(simulation_project, os.path.abspath(update_from), records, members, build_tables)
        header.update(header_fields)
    else:
        header.update(updates=0)
    if header["updates"] == 0:
        header["full_commit"] = header["commit"]
    if not records:
        raise Exception(f"No records of the test map in {', '.join(records_folders)}")
    write_test_map(records, build_tables, simulation_project.get_full_path("."), output_folder, header=header,
                   release_only_blocks=get_release_only_blocks(simulation_project), members=members)
    write_test_map_build_tables(build_tables, os.path.join(output_folder, TEST_MAP_BUILD_TABLES_FILE))
    if differences:
        for key, run_differences in sorted(differences.items()):
            _logger.error(f"Check V5: the run {key} differs from the old map, which the selection did not select it for: {'; '.join(run_differences)}")
        raise Exception(f"Check V5 failed: the new records of {len(differences)} runs that the selection did not give differ from the old map; the map is written")
    return result
