"""
The build tables of the test map. They come from the coverage build of the map commit, once for each
map:

- the function table: for each function of the project's C++ sources, its name, the source file
  and the line range of its body, from the coverage mapping (``llvm-cov export``);
- the emitter table: for each function, the translation units whose object file holds its code. An
  object file that holds code of an instrumented function also defines its profile counter
  ``__profc_<name>`` (``nm --defined-only``), also when the compiler inlined all calls or emitted
  a constructor under another name. The linker keeps one copy of an inline or template function,
  so the binary does not tell which translation units emit it;
- the include table: for each translation unit, the project headers that it includes, from the
  ``.d`` files of the build.

See the test selection plan of opp_repl (``plan/pending/test-selection.md``, section 5.1).
"""

import collections
import concurrent.futures
import glob
import gzip
import json
import logging
import os
import re
import subprocess
import time

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

TEST_MAP_BUILD_TABLES_VERSION = 1

_SOURCE_EXTENSIONS = [".cc", ".cpp", ".cxx", ".c"]

_COUNTER_PREFIX = "__profc_"

def get_counter_symbol(function_name):
    """
    Returns the symbol of the profile counters of a function of the coverage mapping. A function with
    internal linkage has the name ``<source file>:<symbol>`` (or ``;``), and LLVM replaces the
    characters that an assembler does not accept with ``_`` in the symbol, for example
    ``__profc_SGP4.cc__ZN9SGP4FuncsL5initlE...`` for ``SGP4.cc:_ZN9SGP4FuncsL5initlE...``.
    """
    return _COUNTER_PREFIX + re.sub(r"[-:;<>/\"']", "_", function_name)

def read_function_table(export_data, root_folder):
    """
    Returns the function table from the JSON of ``llvm-cov export -format=text``: a list of
    ``[name, file, first line, last line]``, with the file relative to *root_folder* (a real path).
    The line range is the range of the code regions in the file of the function (file 0). A function
    outside the root is left out.
    """
    root = os.path.join(root_folder, "")
    real_paths = {}
    table = []
    for function in export_data["data"][0]["functions"]:
        file_name = function["filenames"][0]
        real_path = real_paths.get(file_name)
        if real_path is None:
            real_path = real_paths[file_name] = os.path.realpath(file_name)
        if not real_path.startswith(root):
            continue
        # a region: [first line, first column, last line, last column, count, file id, expanded file id, kind]
        lines = [(region[0], region[2]) for region in function["regions"] if region[5] == 0]
        if not lines:
            continue
        table.append([function["name"], real_path[len(root):], min(first for first, _ in lines), max(last for _, last in lines)])
    return table

def get_object_folders(simulation_project, mode="coverage"):
    """Returns ``(cpp folder, object folder)`` for each C++ folder of the project, both relative to the project root."""
    makefile_inc_config = simulation_project.get_omnetpp_project().get_makefile_inc_config(mode=mode)
    return [(cpp_folder, os.path.join("out", makefile_inc_config.configname, cpp_folder)) for cpp_folder in simulation_project.cpp_folders]

def get_translation_unit(root_folder, cpp_folder, object_folder, object_file):
    """Returns the source file of an object file, relative to the root."""
    base = os.path.join(cpp_folder, os.path.relpath(object_file, os.path.join(root_folder, object_folder))[:-2])
    for extension in _SOURCE_EXTENSIONS:
        if os.path.exists(os.path.join(root_folder, base + extension)):
            return base + extension
    return base + ".cc"

# a line of "nm --defined-only -A": <object file>:<address> <type> <symbol>
_NM_COUNTER_LINE = re.compile(r"^(.+?):[0-9a-fA-F]* [A-Za-z] (" + _COUNTER_PREFIX + r"\S+)$", re.M)

def read_nm_counters(output):
    """Returns the profile counter symbols (``__profc_...``) of each object file in the output of ``nm --defined-only -A``."""
    result = collections.defaultdict(set)
    # one regular expression over the whole output: most lines are other symbols, and a Python loop over them is slow
    for object_file, symbol in _NM_COUNTER_LINE.findall(output):
        result[object_file].add(symbol)
    return result

def read_dependency_file(text, root_folder, cpp_folder):
    """Returns the translation unit and the project headers of the text of a ``.d`` file. The paths of the file are relative to *cpp_folder*."""
    text = text.replace("\\\n", " ")
    _, _, dependencies = text.partition(": ")
    translation_unit = None
    headers = []
    root = os.path.join(root_folder, "")
    for dependency in dependencies.split():
        if dependency.endswith(":"):
            break # the phony targets of -MP start after the first rule
        path = os.path.realpath(dependency if os.path.isabs(dependency) else os.path.join(root_folder, cpp_folder, dependency))
        if not path.startswith(root):
            continue
        path = path[len(root):]
        if translation_unit is None and os.path.splitext(path)[1] in _SOURCE_EXTENSIONS:
            translation_unit = path
        elif translation_unit is not None:
            headers.append(path)
    return translation_unit, sorted(set(headers))

def make_test_map_build_tables(simulation_project, profile_file, mode="coverage", num_threads=None):
    """
    Makes the build tables of the coverage build of *simulation_project* (see the module
    documentation). *profile_file* is any ``.profdata`` of this build; ``llvm-cov export`` lists all
    functions, also those that no run reached.

    Returns (dict):
        ``{"version", "functions", "emitters", "includes"}``: ``functions`` is the function table,
        ``emitters`` maps the index of a function in the table to its translation units if they are
        not only the source file of the function, and ``includes`` maps each translation unit to its
        project headers.
    """
    from opp_repl.test.coverage import get_coverage_objects, get_coverage_tool, get_coverage_tool_env
    num_threads = num_threads or os.cpu_count()
    start_time = time.time()
    root_folder = os.path.realpath(simulation_project.get_full_path("."))
    # the function table
    objects = get_coverage_objects(simulation_project, mode=mode)
    sources = [simulation_project.get_full_path(folder) for folder in simulation_project.cpp_folders]
    args = [get_coverage_tool(simulation_project, "llvm-cov", mode=mode), "export", "-format=text", "-skip-expansions",
            f"-instr-profile={profile_file}", objects[0], *[f"-object={o}" for o in objects[1:]], *sources]
    _logger.info(" ".join(args))
    result = subprocess.run(args, capture_output=True, text=True, env=get_coverage_tool_env())
    if result.returncode != 0:
        raise Exception("Exporting the function table of the test map failed:\n" + result.stderr[-2000:])
    functions = read_function_table(json.loads(result.stdout), root_folder)
    del result
    _logger.info(f"The function table has {len(functions)} functions ({time.time() - start_time:.1f} s)")
    # the emitter table
    object_files = []
    for cpp_folder, object_folder in get_object_folders(simulation_project, mode=mode):
        for object_file in sorted(glob.glob(os.path.join(root_folder, object_folder, "**", "*.o"), recursive=True)):
            object_files.append((cpp_folder, object_folder, object_file))
    def read_objects(chunk):
        result = subprocess.run(["nm", "--defined-only", "-A", *[object_file for _, _, object_file in chunk]], capture_output=True, text=True, errors="replace")
        if result.returncode != 0:
            raise Exception("Reading the symbols of the objects failed:\n" + result.stderr[-2000:])
        counters = read_nm_counters(result.stdout)
        return [(get_translation_unit(root_folder, cpp_folder, object_folder, object_file), counters.get(object_file, set()))
                for cpp_folder, object_folder, object_file in chunk]
    chunks = [object_files[i:i + 32] for i in range(0, len(object_files), 32)]
    symbol_units = collections.defaultdict(set)
    with concurrent.futures.ThreadPoolExecutor(num_threads) as executor:
        for chunk_result in executor.map(read_objects, chunks):
            for translation_unit, defined in chunk_result:
                for symbol in defined:
                    symbol_units[symbol].add(translation_unit)
    emitters = {}
    for index, (name, file_name, _, _) in enumerate(functions):
        units = symbol_units.get(get_counter_symbol(name), set())
        if units and units != {file_name}:
            emitters[str(index)] = sorted(units)
    _logger.info(f"The emitter table has {len(emitters)} entries ({time.time() - start_time:.1f} s)")
    # the include table
    includes = {}
    for cpp_folder, object_folder in get_object_folders(simulation_project, mode=mode):
        for dependency_file in sorted(glob.glob(os.path.join(root_folder, object_folder, "**", "*.d"), recursive=True)):
            with open(dependency_file, errors="replace") as f:
                translation_unit, headers = read_dependency_file(f.read(), root_folder, cpp_folder)
            if translation_unit:
                includes[translation_unit] = headers
    _logger.info(f"The include table has {len(includes)} translation units ({time.time() - start_time:.1f} s)")
    return {"version": TEST_MAP_BUILD_TABLES_VERSION, "functions": functions, "emitters": emitters, "includes": includes}

def write_test_map_build_tables(build_tables, file_name):
    """Writes the build tables as gzip-compressed JSON."""
    with gzip.open(file_name, "wt") as f:
        json.dump(build_tables, f, separators=(",", ":"))

def read_test_map_build_tables(file_name):
    with gzip.open(file_name, "rt") as f:
        build_tables = json.load(f)
    if build_tables.get("version") != TEST_MAP_BUILD_TABLES_VERSION:
        raise Exception(f"The build tables {file_name} have version {build_tables.get('version')}, expected {TEST_MAP_BUILD_TABLES_VERSION}")
    return build_tables
