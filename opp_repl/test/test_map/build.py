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
  ``.d`` files of the build;
- the NED type table: for each NED type of the project's NED folders, its file and the types that
  it refers to by ``extends``, by ``like`` in its declaration, and by ``like`` in its submodules and
  connections, resolved with the rules of omnetpp (``opp_nedtool`` gives the syntax tree).

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
import tempfile
import time
import xml.etree.ElementTree

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

_NED_TYPE_TAGS = {"simple-module", "compound-module", "module-interface", "channel", "channel-interface"}

def _get_ned_wildcard_regex(import_spec):
    # the PatternMatcher of omnetpp for an import: "**" matches across dots, "*" and "?" do not
    regex = re.escape(import_spec).replace(r"\*\*", ".*").replace(r"\*", "[^.]*").replace(r"\?", "[^.]")
    return re.compile(regex + "$")

def read_ned_type_table(ned_xml):
    """
    Returns the NED type table from the XML of ``opp_nedtool c -x -m``: ``({qualified name: [file,
    [referred types]]}, [unresolved references])``. The referred types are the resolved names of
    ``extends`` and of ``like`` in the declaration, and of the ``like`` interfaces of the submodules
    and connections. The names resolve as in omnetpp (``NedResourceCache::lookupNedType``): a name
    with a dot is fully qualified; a simple name is an inner type of the enclosing compound module,
    then an exactly imported type, then a type of the same package, then a type of a wildcard
    import. omnetpp takes the first match of a wildcard import, so the table takes all matches.
    """
    types = {}
    def add(element, ned_file, package, imports, outer_qname, outer_is_inner):
        qname = (outer_qname + "." if outer_qname else (package + "." if package else "")) + element.get("name")
        types[qname] = {"element": element, "file": ned_file, "package": package, "imports": imports, "outer": outer_qname}
        for types_element in element.findall("types"):
            for inner in types_element:
                if inner.tag in _NED_TYPE_TAGS:
                    add(inner, ned_file, package, imports, qname, outer_qname is not None)
    for ned_file in ned_xml.iter("ned-file"):
        package_element = ned_file.find("package")
        package = package_element.get("name") if package_element is not None else ""
        imports = [element.get("import-spec") for element in ned_file.findall("import")]
        for element in ned_file:
            if element.tag in _NED_TYPE_TAGS:
                add(element, ned_file.get("filename"), package, imports, None, False)
    by_simple_name = collections.defaultdict(list)
    for qname in types:
        by_simple_name[qname.rsplit(".", 1)[-1]].append(qname)
    wildcard_regexes = {}
    def lookup(name, info, inner_context_qname):
        if "." in name:
            return [name] if name in types else []
        if inner_context_qname is not None and inner_context_qname + "." + name in types:
            return [inner_context_qname + "." + name]
        for import_spec in info["imports"]:
            if import_spec in types and (import_spec.endswith("." + name) or import_spec == name):
                return [import_spec]
        qname = info["package"] + "." + name if info["package"] else name
        if qname in types:
            return [qname]
        matches = set()
        for import_spec in info["imports"]:
            if "*" in import_spec or "?" in import_spec:
                regex = wildcard_regexes.setdefault(import_spec, _get_ned_wildcard_regex(import_spec))
                matches.update(q for q in by_simple_name.get(name, []) if regex.match(q))
        return sorted(matches)
    table = {}
    unresolved = set()
    for qname, info in types.items():
        element = info["element"]
        referred = set()
        def refer(name, inner_context_qname):
            resolved = lookup(name, info, inner_context_qname)
            if resolved:
                referred.update(resolved)
            else:
                unresolved.add(name)
        # extends and like of the declaration: the context is the parent, so an inner type can
        # refer to the other inner types of its compound module
        declaration_context = info["outer"] if info["outer"] and types[info["outer"]]["element"].tag == "compound-module" else None
        for tag in ("extends", "interface-name"):
            for child in element.findall(tag):
                refer(child.get("name"), declaration_context)
        # like of the submodules and connections: the context is the compound module itself, or
        # its top-level type if it is an inner type
        if element.tag == "compound-module":
            body_context = info["outer"] or qname
            for child in element.iter():
                if child.tag in ("submodule", "connection") and child.get("like-type"):
                    refer(child.get("like-type"), body_context)
        table[qname] = [info["file"], sorted(referred - {qname})]
    return table, sorted(unresolved)

def get_ned_type_closure(instantiated_types, ned_types):
    """
    Returns the NED types that a run used: its instantiated types, and the types that they refer to
    in the NED type table, recursively (the base types, the interfaces, and the interfaces of their
    ``like`` submodules and connections). A type that is not in the table (for example ``ned.*``)
    stays in the result, without its references.
    """
    result = set()
    stack = list(instantiated_types)
    while stack:
        qname = stack.pop()
        if qname not in result:
            result.add(qname)
            entry = ned_types.get(qname)
            if entry:
                stack.extend(entry[1])
    return result

def make_ned_type_table(simulation_project):
    """Returns the NED type table of the project's NED folders (see :py:func:`read_ned_type_table`), and the errors of ``opp_nedtool``."""
    omnetpp_project = simulation_project.get_omnetpp_project()
    nedtool = os.path.join(omnetpp_project.get_root_path(), "bin", "opp_nedtool")
    root_folder = simulation_project.get_full_path(".")
    with tempfile.TemporaryDirectory(dir=root_folder) as folder:
        output_file = os.path.join(folder, "ned.xml")
        args = [nedtool, "c", "-x", "-m", "-o", output_file, *simulation_project.ned_folders]
        result = subprocess.run(args, cwd=root_folder, env=omnetpp_project.get_env(), capture_output=True, text=True)
        if not os.path.exists(output_file):
            raise Exception("Converting the NED files to XML failed:\n" + (result.stdout + result.stderr)[-2000:])
        table, unresolved = read_ned_type_table(xml.etree.ElementTree.parse(output_file).getroot())
    errors = [line for line in (result.stdout + result.stderr).splitlines() if "Error" in line]
    return table, unresolved, errors

def make_test_map_build_tables(simulation_project, profile_file, mode="coverage", num_threads=None):
    """
    Makes the build tables of the coverage build of *simulation_project* (see the module
    documentation). *profile_file* is any ``.profdata`` of this build; ``llvm-cov export`` lists all
    functions, also those that no run reached.

    Returns (dict):
        ``{"version", "functions", "emitters", "includes"}``: ``functions`` is the function table,
        ``emitters`` maps the index of a function in the table to its translation units if they are
        not only the source file of the function, ``includes`` maps each translation unit to its
        project headers, ``ned_types`` is the NED type table, ``ned_unresolved`` lists the NED type
        references that did not resolve (for example the omnetpp types ``ned.*``), and ``ned_errors``
        holds the errors of ``opp_nedtool`` (a NED file with a syntax error is not in the table).
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
    ned_types, ned_unresolved, ned_errors = make_ned_type_table(simulation_project)
    _logger.info(f"The NED type table has {len(ned_types)} types ({time.time() - start_time:.1f} s)")
    return {"version": TEST_MAP_BUILD_TABLES_VERSION, "functions": functions, "emitters": emitters, "includes": includes,
            "ned_types": ned_types, "ned_unresolved": ned_unresolved, "ned_errors": ned_errors}

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
