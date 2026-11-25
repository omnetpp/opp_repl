"""
Queries of the test map (see :py:mod:`opp_repl.test.test_map.writer`): which tests used a file, a
function at a line, or the files below a folder, and what the tests that match a filter used.
"""

import json
import os
import re
import sys

__sphinx_mock__ = True # ignore this module in documentation

_TABLE_FILES = {"runs.json", "tests.json", "header.json", "emitter-sets.json"}

def read_test_map_file(map_folder, path):
    """Returns the content of the map file of *path* (a source file), or None if the map has none."""
    file_name = os.path.join(map_folder, path + ".json")
    if not os.path.exists(file_name):
        return None
    with open(file_name) as f:
        return json.load(f)

def expand_run_set(run_set, all_run_ids):
    """Returns the run ids of a run set of the map: ``"all"``, ``{"except": [...]}`` or a list."""
    if run_set == "all":
        return set(all_run_ids)
    if isinstance(run_set, dict):
        return set(all_run_ids) - set(run_set["except"])
    return set(run_set or [])

def get_tests_of_runs(tests, run_ids):
    """Returns ``{kind: [test keys]}`` of the tests that start one of *run_ids*."""
    result = {}
    for kind, kind_tests in sorted(tests.items()):
        keys = sorted(key for key, ids in kind_tests.items() if run_ids & set(ids))
        if keys:
            result[kind] = keys
    return result

def _get_file_run_ids(obj, all_run_ids):
    run_ids = set()
    for item in obj.get("functions", []):
        run_ids |= expand_run_set(item.get("runs"), all_run_ids)
    for part in ("types", "sections", "data"):
        for run_set in obj.get(part, {}).values():
            run_ids |= expand_run_set(run_set, all_run_ids)
    return run_ids

def show_test_map(map_folder, path=None, line=None, list_tests=False, test_filter=None, output_stream=sys.stdout):
    """
    Prints a query of the test map in *map_folder*:

    - *path* of a folder: the number of runs that used something below it, for each kind.
    - *path* of a file: the parts of its map file (functions, translation unit, includes, NED types,
      ini sections, data) with the number of runs of each part. With *line*, the tests that ran the
      function whose body has the line. With *list_tests*, the tests that used any part of the file.
    - *test_filter*: a regular expression of run keys. The files that these runs used, with the
      parts.
    """
    def load(name):
        with open(os.path.join(map_folder, name)) as f:
            return json.load(f)
    runs = load("runs.json")
    tests = load("tests.json")
    header = load("header.json")
    all_run_ids = sorted(runs)
    def count(run_set):
        return len(expand_run_set(run_set, all_run_ids))
    def print_tests(run_ids):
        for kind, keys in get_tests_of_runs(tests, run_ids).items():
            print(f"{kind}: {len(keys)} tests", file=output_stream)
            for key in keys:
                print(f"  {key}", file=output_stream)
    print(f"Test map of {header.get('project')} at {header.get('commit')}, {header.get('runs')} runs, {header.get('date')}", file=output_stream)
    if test_filter:
        run_ids = {run_id for run_id, run in runs.items() if re.search(test_filter, run["key"])}
        print(f"{len(run_ids)} runs match {test_filter!r}", file=output_stream)
        for folder, _, file_names in sorted(os.walk(map_folder)):
            for file_name in sorted(file_names):
                if file_name == "index.json" or (folder == map_folder and file_name in _TABLE_FILES):
                    continue
                with open(os.path.join(folder, file_name)) as f:
                    obj = json.load(f)
                parts = []
                functions = [item for item in obj.get("functions", []) if run_ids & expand_run_set(item.get("runs"), all_run_ids)]
                if functions:
                    parts.append(f"{len(functions)} functions")
                for part in ("types", "sections", "data"):
                    names = [name for name, run_set in obj.get(part, {}).items() if run_ids & expand_run_set(run_set, all_run_ids)]
                    if names:
                        parts.append(f"{part} {', '.join(names)}")
                if parts:
                    print(f"{os.path.relpath(os.path.join(folder, file_name), map_folder)[:-5]}: {'; '.join(parts)}", file=output_stream)
        return
    path = os.path.normpath(path or ".")
    obj = read_test_map_file(map_folder, path) if path != "." else None
    if obj is None:
        index_file = os.path.join(map_folder, path, "index.json")
        if not os.path.exists(index_file):
            print(f"{path}: no run used it", file=output_stream)
            return
        with open(index_file) as f:
            index = json.load(f)
        for kind, value in index.items():
            print(f"{path}: {kind}: {count(value) if kind == 'listed' else value} runs", file=output_stream)
        return
    if line is not None:
        items = [item for item in obj.get("functions", []) if item["lines"][0] <= line <= item["lines"][1]]
        if not items:
            print(f"{path}:{line}: in no function body", file=output_stream)
        for item in items:
            run_ids = expand_run_set(item.get("runs"), all_run_ids)
            print(f"{path}:{item['lines'][0]}-{item['lines'][1]} {item['name']}: {len(run_ids)} runs", file=output_stream)
            print_tests(run_ids)
        return
    functions = obj.get("functions", [])
    if functions:
        ran = [item for item in functions if item.get("runs")]
        print(f"functions: {len(ran)} of {len(functions)} ran", file=output_stream)
        for item in ran:
            print(f"  {item['lines'][0]}-{item['lines'][1]} {item['name']}: {count(item['runs'])} runs", file=output_stream)
    if "tu_runs" in obj:
        print(f"translation unit: {count(obj['tu_runs'])} runs ran a function that it emits", file=output_stream)
    if "included_by" in obj:
        print(f"included by {len(obj['included_by'])} translation units", file=output_stream)
    for part in ("types", "sections", "data"):
        if part in obj:
            print(f"{part}:", file=output_stream)
            for name, run_set in obj[part].items():
                print(f"  {name}: {count(run_set)} runs", file=output_stream)
    if list_tests:
        print_tests(_get_file_run_ids(obj, all_run_ids))
