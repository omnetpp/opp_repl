"""
The change-based test selection: reads the test map and the changes, and selects each test that the
map cannot prove to be unaffected (see the test selection plan of opp_repl,
``plan/pending/test-selection.md``, sections 4, 5 and 9).

The selection reads diff(A,B) and diff(A,C), where A is the map commit, B the base and C the target
of the change (:py:class:`opp_repl.test.test_map.changes.Changes`). A test that it does not select has
the same outcome at C as at B, if the assumptions of section 4.4 of the plan are true.

The main function is :py:func:`select_tests`.
"""

import ast
import collections
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree

from opp_repl.test.test_map.build import read_ned_type_table
from opp_repl.test.test_map.changes import WORKTREE, Changes, Side, get_file_changes, is_commit, _git
from opp_repl.test.test_map.ndebug import get_simple_function_name
from opp_repl.test.test_map.writer import TEST_MAP_VERSION, get_default_test_map_folder

__sphinx_mock__ = True # ignore this module in documentation

_logger = logging.getLogger(__name__)

SOURCE_EXTENSIONS = {".cc", ".cpp", ".cxx", ".c", ".C"}
HEADER_EXTENSIONS = {".h", ".hh", ".hpp", ".hxx", ".inl", ".tcc", ".ipp"}
# the build reads these files in the project root and in the C++ folders (rule R11)
BUILD_FILE_NAMES = {"Makefile", "makefrag", ".oppbuildspec", ".oppfeatures", ".oppfeaturestate", ".nedfolders", ".nedexclusions"}
# fields of a .opp file that do not change the outcome of a test
HARMLESS_PROJECT_FIELDS = {"github_owner", "github_repository", "github_workflows"}
# the test_parameters kinds that do not run tests
NON_TEST_KINDS = {"coverage"}
# files of a harness commit that do not change the outcome of a test (rules H1 and H5)
HARMLESS_HARNESS_FILES = re.compile(r"(^|/)(doc|plan|\.github)/|\.md$|^opp_repl/test/test_map/|^opp_repl/test/self/|^ui/")
# the number of reasons that a test keeps for the explanation
MAX_REASONS = 5
# The kinds whose expected outcome is a text output, which can hold a line number: __LINE__ goes only
# into log lines, error messages and the names of static objects, so a line shift (rule R3) changes
# only these kinds. A fingerprint, a statistical result, a chart, a speed and the end status of a run
# do not hold these texts.
LINE_SENSITIVE_KINDS = {"opp", "unit", "module", "packet", "queueing", "protocol"}

class Reason(collections.namedtuple("Reason", ["rule", "path", "detail", "side"])):
    """Why a test is selected: the rule of the plan, the changed file, a detail, and the diff (``A..B`` or ``A..C``)."""
    def __str__(self):
        text = self.rule + (" " + self.path if self.path else "") + (": " + self.detail if self.detail else "")
        return text + (f" ({self.side})" if self.side else "")

#
# C++ tokens
#

def tokenize_cpp_lines(text):
    """
    Returns, for each line of the C++ text, the tokens that start on it, without comments and white
    space. White space between two punctuation characters, and each white space in a preprocessor
    directive, is a token ``" "``, and the end of a directive is a token ``"<eod>"``. So two texts
    have the same tokens only if they differ only in comments and in white space that the compiler
    ignores.
    """
    lines = text.split("\n")
    tokens = [[] for _ in lines]
    length = len(text)
    index = 0
    line = 0
    at_line_start = True
    in_directive = False
    space = False
    last_kind = None
    def emit(token, kind, start_line):
        nonlocal space, last_kind
        if space and (in_directive or (kind == "p" and last_kind == "p")):
            tokens[start_line].append(" ")
        tokens[start_line].append(token)
        space = False
        last_kind = kind
    def read_literal(start):
        # a string or character literal that starts at start; returns its end
        quote = text[start]
        position = start + 1
        while position < length and text[position] != quote:
            if text[position] == "\\":
                position += 2
            elif text[position] == "\n":
                break
            else:
                position += 1
        return min(position + 1, length)
    while index < length:
        char = text[index]
        if char == "\\" and text.startswith("\n", index + 1):
            # a line splice
            index += 2
            line += 1
            continue
        if char == "\n":
            if in_directive:
                tokens[line].append("<eod>")
                in_directive = False
            line += 1
            index += 1
            at_line_start = True
            space = True
            continue
        if char in " \t\r\f\v":
            space = True
            index += 1
            continue
        if text.startswith("//", index):
            while index < length and text[index] != "\n":
                if text[index] == "\\" and text.startswith("\n", index + 1):
                    index += 2
                    line += 1
                else:
                    index += 1
            space = True
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = length if end < 0 else end + 2
            line += text.count("\n", index, end)
            index = end
            space = True
            continue
        start_line = line
        if char == "#" and at_line_start:
            at_line_start = False
            emit("#", "p", start_line)
            in_directive = True
            index += 1
            continue
        at_line_start = False
        if char.isalpha() or char in "_$" or ord(char) > 127:
            end = index
            while end < length and (text[end].isalnum() or text[end] in "_$" or ord(text[end]) > 127):
                end += 1
            word = text[index:end]
            if end < length and text[end] == '"' and word in ("R", "u8R", "uR", "UR", "LR"):
                # a raw string literal: R"delimiter(...)delimiter"
                open_paren = text.find("(", end + 1)
                close = text.find(")" + text[end + 1:open_paren] + '"', open_paren + 1) if open_paren >= 0 else -1
                end = length if close < 0 else close + open_paren - end + 1
                end = min(end, length)
            elif end < length and text[end] in "\"'" and word in ("u8", "u", "U", "L"):
                end = read_literal(end)
            literal = text[index:end]
            line += literal.count("\n")
            emit(literal, "w", start_line)
            index = end
            continue
        if char.isdigit() or (char == "." and index + 1 < length and text[index + 1].isdigit()):
            end = index + 1
            while end < length:
                if text[end] in "eEpP" and end + 1 < length and text[end + 1] in "+-":
                    end += 2
                elif text[end].isalnum() or text[end] in "._'":
                    end += 1
                else:
                    break
            emit(text[index:end], "w", start_line)
            index = end
            continue
        if char in "\"'":
            end = read_literal(index)
            literal = text[index:end]
            line += literal.count("\n")
            emit(literal, "w", start_line)
            index = end
            continue
        emit(char, "p", start_line)
        index += 1
    return tokens

def get_trivial_hunks(old_tokens, new_tokens, hunks):
    """
    Returns, for each hunk, True if it changes only comments and white space (rules R1 and R3). If a
    line outside the hunks has other tokens at the two sides, an opened comment or literal changed
    the meaning of other lines, and no hunk is trivial.
    """
    def hunk_tokens(tokens, start, count):
        return [token for line in range(start - 1, start - 1 + count) for token in tokens[line]] if count else []
    trivial = [hunk_tokens(old_tokens, s, c) == hunk_tokens(new_tokens, t, d) for s, c, t, d in hunks]
    old_line = new_line = 0
    for s, c, t, d in list(hunks) + [(len(old_tokens) + 1, 0, len(new_tokens) + 1, 0)]:
        old_end = s - 1 if c else s
        new_end = t - 1 if d else t
        if old_end - old_line != new_end - new_line and (s, c) != (len(old_tokens) + 1, 0):
            return [False] * len(hunks)
        while old_line < min(old_end, len(old_tokens)) and new_line < min(new_end, len(new_tokens)):
            if old_tokens[old_line] != new_tokens[new_line]:
                return [False] * len(hunks)
            old_line += 1
            new_line += 1
        old_line = old_end + c
        new_line = new_end + d
    return trivial

def _is_inside(lines, start, count):
    # the hunk is inside the body, not on the line of its opening or closing brace
    first, last = lines
    return first < start and start + count - 1 < last if count else first <= start < last

def _is_lambda(name):
    return "::$_" in name or "{lambda(" in name

def _has_compile_time_body(tokens, function, functions):
    """
    True if the body of a function can change other code: a ``constexpr`` or ``consteval`` function
    (the compiler can evaluate it, rule R5), or a deduced return type. It examines the lines between
    the end of the function before it and the opening brace of the body, so it can find too much.
    """
    first = function["lines"][0]
    previous_last = max([other["lines"][1] for other in functions if other["lines"][1] < first] + [first - 20])
    window = []
    for line in range(max(previous_last, 0), min(first, len(tokens))):
        window.extend(tokens[line])
    if "constexpr" in window or "consteval" in window:
        return True
    arrow = any(a == "-" and b == ">" for a, b in zip(window, window[1:]))
    return "auto" in window and not arrow

#
# ini files
#

def _strip_ini_comment(line):
    in_string = False
    for index, char in enumerate(line):
        if char == '"' and (index == 0 or line[index - 1] != "\\"):
            in_string = not in_string
        elif char == "#" and not in_string:
            return line[:index]
    return line

# a key of opp_repl in a comment line of an ini file, as opp_repl reads it: "#expected-result = ..."
_INI_COMMENT_DIRECTIVE = re.compile(r"#\s*(abstract|emulation|expected-result|bounded)\s*=(.*)$")

def read_ini_sections(text):
    """
    Returns the entries of each section of an ini file, ``({section: [(key, value)]}, error)``. The
    section names are as in ``-q sectioninheritance``: ``General`` or ``Config <name>``. The entries
    before the first section belong to ``General``; an ``include`` line is an entry. *error* is the
    first line that is not a section, an entry, or an include, or None. A comment line with a key
    that opp_repl reads (``#expected-result``, ``#abstract``, ``#emulation``, ``#bounded``) is an
    entry with the key ``#<key>`` (rule I4).
    """
    sections = {}
    current = "General"
    error = None
    logical_line = ""
    for number, line in enumerate(text.split("\n"), 1):
        # rule I4: opp_repl reads these keys also from a comment (simulation/project.py), and they
        # decide if a config is a test and its expected result, so they are entries of the section
        directive = None if logical_line else _INI_COMMENT_DIRECTIVE.match(line)
        if directive:
            sections.setdefault(current, []).append(("#" + directive.group(1), directive.group(2).strip()))
            continue
        line = _strip_ini_comment(logical_line + line) if not logical_line else logical_line + _strip_ini_comment(line)
        if line.rstrip().endswith("\\"):
            logical_line = line.rstrip()[:-1]
            continue
        logical_line = ""
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("["):
            if not stripped.endswith("]"):
                error = error or f"line {number}: {stripped}"
                continue
            name = " ".join(stripped[1:-1].split())
            current = name if name == "General" or name.startswith("Config ") else "Config " + name
            sections.setdefault(current, [])
        elif re.match(r"include\s", stripped):
            sections.setdefault(current, []).append(("include", stripped[len("include"):].strip()))
        elif "=" in stripped:
            key, _, value = stripped.partition("=")
            sections.setdefault(current, []).append((key.strip(), value.strip()))
        else:
            error = error or f"line {number}: {stripped}"
            sections.setdefault(current, []).append(("", stripped))
    return sections, error

def _is_iteration_entry(entry):
    # the entries that change the runs of a config: iteration variables, repeat and constraint (rule I3)
    key, value = entry
    return "$" in key or "$" in value or key in ("repeat", "constraint")

#
# NED files
#

def read_ned_declared_types(texts, omnetpp_project, packages=None):
    """
    Returns the NED types that the NED texts declare, ``({path: set of qualified names}, {path:
    error})``. *texts* maps a path, relative to the project root, to its text. ``opp_nedtool`` parses
    the texts; a text that it cannot parse has an error. If *packages* is a dict, it gets the declared
    package of each path.
    """
    if not texts:
        return {}, {}
    nedtool = os.path.join(omnetpp_project.get_root_path(), "bin", "opp_nedtool")
    with tempfile.TemporaryDirectory() as folder:
        for path, text in texts.items():
            full_path = os.path.join(folder, path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", errors="surrogateescape") as f:
                f.write(text)
        output_file = os.path.join(folder, "ned.xml")
        result = subprocess.run([nedtool, "c", "-x", "-m", "-o", output_file, *texts], cwd=folder, env=omnetpp_project.get_env(), capture_output=True, text=True)
        output = result.stdout + result.stderr
        errors = {}
        for line in output.splitlines():
            for path in texts:
                if line.startswith(path + ":"):
                    errors.setdefault(path, line)
        types = {path: set() for path in texts}
        if os.path.exists(output_file):
            root = xml.etree.ElementTree.parse(output_file).getroot()
            table, _ = read_ned_type_table(root)
            for qname, (path, _) in table.items():
                types.setdefault(path, set()).add(qname)
            if packages is not None:
                for ned_file in root.iter("ned-file"):
                    package = ned_file.find("package")
                    packages[ned_file.get("filename")] = package.get("name") if package is not None else ""
        elif not errors:
            errors = {path: output.strip()[-500:] or "opp_nedtool failed" for path in texts}
    return types, errors

_NED_DECLARATION = r"^\s*(simple|module|network|channel|moduleinterface|channelinterface)\s+{}\b"

def _read_ned_package(text):
    # the declared package of a NED text, without the comments
    match = re.search(r"^\s*package\s+([\w.]+)\s*;", re.sub(r"//.*", "", text or ""), re.MULTILINE)
    return match.group(1) if match else ""

def get_expected_ned_package(path, ned_folders, side):
    """
    Returns the package that omnetpp expects for a NED file (``NedResourceCache::getNedPackageForFolder``):
    the package of ``package.ned`` in the root of its NED folder at *side*, and the folders below it.
    """
    folder = max((folder for folder in ned_folders if folder in (".", "") or path.startswith(folder + "/")), key=len, default=None)
    if folder is None:
        return None
    root = "" if folder in (".", "") else folder
    root_package = _read_ned_package(side.read(os.path.join(root, "package.ned")) if root else side.read("package.ned"))
    relative = os.path.relpath(os.path.dirname(path), root or ".")
    subpackage = "" if relative == "." else relative.replace("/", ".")
    return ".".join(part for part in (root_package, subpackage) if part)

#
# the map
#

class TestMap:
    """A test map of :py:func:`opp_repl.test.test_map.writer.write_test_map`, read on demand."""
    def __init__(self, folder):
        self.folder = folder
        header_file = os.path.join(folder, "header.json")
        if not os.path.exists(header_file):
            raise Exception(f"{folder} holds no test map (no header.json)")
        self.header = self._read_json("header.json")
        if self.header.get("version", 0) > TEST_MAP_VERSION:
            raise Exception(f"The test map in {folder} has version {self.header['version']}, this opp_repl reads up to version {TEST_MAP_VERSION}")
        self.runs = self._read_json("runs.json")
        self.run_ids = list(self.runs)
        self.run_index = {run_id: index for index, run_id in enumerate(self.run_ids)}
        self.all = (1 << len(self.run_ids)) - 1
        self.tests = self._read_json("tests.json")
        self.run_tests = collections.defaultdict(list)
        for kind, tests in self.tests.items():
            for key, run_ids in tests.items():
                for run_id in run_ids:
                    self.run_tests[self.run_index[run_id]].append((kind, key))
        self._files = {}
        self._emitter_sets = None
        self._release_only = None
        self._all_files = None
        self._ned_types = None

    def _read_json(self, path):
        with open(os.path.join(self.folder, path), errors="surrogateescape") as f:
            return json.load(f)

    def get(self, path):
        """Returns the map file of the project file *path*, or None."""
        if path not in self._files:
            map_file = os.path.join(self.folder, path + ".json")
            self._files[path] = self._read_json(path + ".json") if os.path.isfile(map_file) else None
        return self._files[path]

    def get_index(self, folder):
        """Returns the ``index.json`` of a project folder ("" for the root), or None."""
        index_file = os.path.join(self.folder, folder, "index.json")
        return self._read_json(os.path.join(folder, "index.json")) if os.path.isfile(index_file) else None

    def bits(self, run_set):
        """Returns a set of runs of the map as a bit set over the run indices."""
        if run_set is None:
            return 0
        if run_set == "all":
            return self.all
        if isinstance(run_set, dict):
            bits = self.all
            for run_id in run_set["except"]:
                bits &= ~(1 << self.run_index[run_id])
            return bits
        bits = 0
        for run_id in run_set:
            bits |= 1 << self.run_index[run_id]
        return bits

    def get_release_only_blocks(self):
        """
        Returns the release-only blocks of the map (rule R-NDEBUG) as ``(blocks by name, blocks by
        included file)``, or None for a map of version 2, which does not list them.
        """
        if self._release_only is None:
            if not os.path.exists(os.path.join(self.folder, "release-only.json")):
                self._release_only = False
            else:
                by_name = collections.defaultdict(list)
                by_include = collections.defaultdict(list)
                for block in self._read_json("release-only.json")["blocks"]:
                    for name in block["names"]:
                        by_name[name].append(block)
                    for include in block["includes"]:
                        by_include[include].append(block)
                self._release_only = (by_name, by_include)
        return self._release_only or None

    def get_emitter_set(self, set_id):
        if self._emitter_sets is None:
            self._emitter_sets = self._read_json("emitter-sets.json")["sets"] if os.path.exists(os.path.join(self.folder, "emitter-sets.json")) else {}
        return self._emitter_sets.get(set_id)

    def get_all_files(self):
        """Returns all map files as ``{path: content}``, without the folder index files and the tables."""
        if self._all_files is None:
            self._all_files = {}
            for folder, _, names in os.walk(self.folder):
                for name in names:
                    if name.endswith(".json") and name != "index.json":
                        path = os.path.relpath(os.path.join(folder, name), self.folder)[:-len(".json")]
                        if path not in ("header", "runs", "tests", "emitter-sets"):
                            self._all_files[path] = self.get(path)
        return self._all_files

    def get_ned_types(self):
        """Returns ``{qualified name: bits of the runs}`` of all NED types of the map."""
        if self._ned_types is None:
            self._ned_types = {}
            for path, content in self.get_all_files().items():
                for qname, run_set in (content or {}).get("types", {}).items():
                    self._ned_types[qname] = self._ned_types.get(qname, 0) | self.bits(run_set)
        return self._ned_types

    def get_ini_file_runs(self, path):
        """Returns the bits of the runs whose ini file is *path*."""
        bits = 0
        for index, run_id in enumerate(self.run_ids):
            run = self.runs[run_id]
            if os.path.normpath(os.path.join(run["working_directory"], run["ini_file"])) == path:
                bits |= 1 << index
        return bits

    def get_abnormal_runs(self):
        return sum(1 << index for index, run_id in enumerate(self.run_ids) if not self.runs[run_id].get("normal_end", True))

#
# the rules
#

class ProjectInfo:
    """The facts of the simulation project that the rules need."""
    def __init__(self, simulation_project):
        self.simulation_project = simulation_project
        self.name = simulation_project.get_name()
        self.root_folder = simulation_project.get_full_path(".")
        self.cpp_folders = [os.path.normpath(folder) for folder in simulation_project.cpp_folders]
        self.msg_folders = [os.path.normpath(folder) for folder in simulation_project.msg_folders]
        self.ned_folders = [os.path.normpath(folder) for folder in simulation_project.ned_folders]
        self.test_parameters = simulation_project.test_parameters or {}
        self.stores = {os.path.normpath(parameters["store"]): kind for kind, parameters in self.test_parameters.items() if isinstance(parameters, dict) and parameters.get("store")}

    def is_below(self, path, folders):
        return any(folder in (".", "") or path == folder or path.startswith(folder + "/") for folder in folders)

    def classify(self, path):
        """Returns the input class of a file (section 5 of the plan)."""
        name = os.path.basename(path)
        extension = os.path.splitext(path)[1]
        if name in BUILD_FILE_NAMES and (os.path.dirname(path) == "" or self.is_below(path, self.cpp_folders)):
            return "build"
        if extension == ".opp":
            return "opp"
        if path in self.stores:
            return "store"
        if (extension in SOURCE_EXTENSIONS or extension in HEADER_EXTENSIONS) and self.is_below(path, self.cpp_folders):
            return "cpp"
        if extension == ".msg" and self.is_below(path, self.msg_folders):
            return "msg"
        if extension == ".ned" and self.is_below(path, self.ned_folders):
            return "ned"
        if extension == ".ini":
            return "ini"
        return "data"

def get_fingerprint_store_test_keys(entries, ingredients_list=None):
    """Returns ``{test key: entry without timestamp}`` of the entries of a fingerprint store; the keys are those of ``tests.json``."""
    result = {}
    for entry in entries:
        if ingredients_list is not None and entry["ingredients"] not in ingredients_list:
            continue
        ini_path = os.path.normpath(os.path.join(entry["working_directory"], entry["ini_file"]))
        key = f"fingerprint:{ini_path}:{entry['config']}:#{entry['run_number']}:{entry['sim_time_limit'] or ''}:{entry['ingredients']}"
        result[key] = {name: value for name, value in entry.items() if name != "timestamp"}
    return result

def _read_opp_fields(text):
    node = ast.parse(text, mode="eval").body
    if not isinstance(node, ast.Call):
        raise ValueError("a .opp file holds one constructor call")
    return {keyword.arg: ast.literal_eval(keyword.value) for keyword in node.keywords}

class SideSelection:
    """The runs and tests that the changes of one diff (A..B or A..C) select."""
    def __init__(self, test_map, side):
        self.test_map = test_map
        self.side = side
        self.entries = [] # (bits, reason)
        self.tests = [] # (kind, key, reason)
        self.kinds = {} # kind -> reason: all tests of the kind
        self.everything = [] # reasons: all tests
        self.files = [] # (path, status, input class, {rule: effect})
        self.header_bits = 0 # the runs of rule R4 for all changed headers
        self._file_rules = None

    def _note(self, rule, runs=0, tests=0, everything=False, kind=None):
        if self._file_rules is not None:
            note = self._file_rules.setdefault(rule, {"runs": 0, "tests": 0, "all": False, "kinds": set()})
            note["runs"] |= runs
            note["tests"] += tests
            note["all"] = note["all"] or everything
            if kind:
                note["kinds"].add(kind)

    def add(self, bits, rule, path, detail=""):
        if bits:
            self.entries.append((bits, Reason(rule, path, detail, self.side)))
            self._note(rule, runs=bits)

    def add_all(self, rule, path, detail=""):
        self.everything.append(Reason(rule, path, detail, self.side))
        self._note(rule, everything=True)

    def add_kind(self, kind, rule, path, detail=""):
        self.kinds.setdefault(kind, Reason(rule, path, detail, self.side))
        self._note(rule, kind=kind)

    def add_test(self, kind, key, rule, path, detail=""):
        self.tests.append((kind, key, Reason(rule, path, detail, self.side)))
        self._note(rule, tests=1)

    def begin_file(self, change, input_class):
        self._file_rules = {}
        self.files.append((change.path, change.status, input_class, self._file_rules))

    def end_file(self):
        self._file_rules = None

def _describe_note(note):
    if note["all"]:
        return "all tests"
    parts = []
    if note["kinds"]:
        parts.append("all " + ", ".join(sorted(note["kinds"])) + " tests")
    if note["runs"]:
        parts.append(f"{note['runs'].bit_count()} runs")
    if note["tests"]:
        parts.append(f"{note['tests']} tests")
    if note.get("headers"):
        parts.append("the runs of the changed headers")
    return ", ".join(parts) or "no tests"

def _select_cpp(selection, change, project, changed_headers):
    test_map = selection.test_map
    path = change.path
    extension = os.path.splitext(path)[1]
    is_source = extension in SOURCE_EXTENSIONS
    entry = test_map.get(path) or {}
    if change.status != "modified":
        if is_source:
            selection.add_all("R7", path, f"a translation unit is {change.status}; the static initialization of each process changes")
        elif change.status == "removed":
            changed_headers[path] = "R9"
        return
    if change.hunks is None:
        if is_source:
            selection.add_all("R6", path, "a binary change")
        else:
            changed_headers[path] = "R4"
        return
    old_text = change.get_old_text() or ""
    new_text = change.get_new_text() or ""
    old_tokens = tokenize_cpp_lines(old_text)
    new_tokens = tokenize_cpp_lines(new_text)
    functions = entry.get("functions", [])
    trivial = get_trivial_hunks(old_tokens, new_tokens, change.hunks)
    for (start, count, new_start, new_count), is_trivial in zip(change.hunks, trivial):
        if is_trivial and count == new_count:
            continue
        end = start + count - 1 if count else start
        if count != new_count:
            # __LINE__ changes below the hunk (ASSERT, error messages)
            below = 0
            for function in functions:
                if function["lines"][1] > end:
                    below |= test_map.bits(function.get("runs"))
            selection.add(below, "R3", path, f"line {start}: the lines below move")
        if is_trivial:
            continue
        containing = [function for function in functions if _is_inside(function["lines"], start, count)]
        compile_time = False
        for function in containing:
            if not _is_lambda(function["name"]) and _has_compile_time_body(old_tokens, function, functions):
                compile_time = True
            elif "runs" in function:
                selection.add(test_map.bits(function["runs"]), "R2", path, f"line {start}: {function['name']}")
                _select_release_only_names(selection, path, start, function)
        if not containing or compile_time:
            if is_source:
                detail = "a constexpr function or a deduced return type" if containing else "outside the function bodies"
                selection.add_all("R5" if containing else "R6", path, f"line {start}: {detail}; the static initialization of each process can change")
            else:
                changed_headers.setdefault(path, "R5" if containing else "R4")

def _describe_block(block):
    return f"the release-only block {block['path']}:{block['lines'][0]}"

def _select_release_only_names(selection, path, start, function):
    # rule R-NDEBUG: a release-only block names the changed function, so a release build can run it
    # also where the map does not record it
    release_only = selection.test_map.get_release_only_blocks()
    if release_only:
        for block in release_only[0].get(get_simple_function_name(function["name"]), []):
            selection.add(selection.test_map.bits(block["runs"]), "R-NDEBUG", path, f"line {start}: {function['name']} is named in {_describe_block(block)}")

def _select_release_only_includes(selection, change):
    # rule R-NDEBUG: a release-only block includes the changed file, which the coverage build does not compile
    release_only = selection.test_map.get_release_only_blocks()
    if release_only:
        for block in release_only[1].get(change.path, []):
            selection.add(selection.test_map.bits(block["runs"]), "R-NDEBUG", change.path, f"{_describe_block(block)} includes the file")

def _select_changed_headers(selection, changed_headers):
    """
    Rule R4: a header changed outside the function bodies. Under the one-definition rule, a function
    can change only if each translation unit that emits it includes a changed header: a translation
    unit without one has the same text at both sides, so its copy of the function, and so all copies,
    stay the same.
    """
    test_map = selection.test_map
    includers = set()
    for header in changed_headers:
        includers.update((test_map.get(header) or {}).get("included_by", []))
    description = ", ".join(sorted(changed_headers)[:3]) + (f" and {len(changed_headers) - 3} more" if len(changed_headers) > 3 else "")
    rule = "R4" if "R4" in changed_headers.values() else sorted(set(changed_headers.values()))[0]
    for path, content in test_map.get_all_files().items():
        if not content or not content.get("functions"):
            continue
        is_source = os.path.splitext(path)[1] in SOURCE_EXTENSIONS
        bits = 0
        count = 0
        for function in content["functions"]:
            if "runs" not in function:
                continue
            units = function.get("tus")
            if units is None:
                emitters = [path] if is_source else []
            elif isinstance(units, list):
                emitters = units
            elif units.get("set") is not None and test_map.get_emitter_set(units["set"]) is not None:
                emitters = test_map.get_emitter_set(units["set"])
            else:
                # a map of version 1 has only the number of emitters: more emitters than includers
                # means that one emitter does not include a changed header
                if units["count"] > len(includers):
                    continue
                emitters = []
            if all(emitter in includers for emitter in emitters):
                bits |= test_map.bits(function["runs"])
                count += 1
        selection.add(bits, rule, description, f"{count} function(s) of {path}")
        selection.header_bits |= bits

def _select_ned(selection, changes, project):
    test_map = selection.test_map
    omnetpp_project = project.simulation_project.get_omnetpp_project()
    old_types, _ = read_ned_declared_types({change.path: change.get_old_text() or "" for change in changes if change.status != "added"}, omnetpp_project)
    new_packages = {}
    new_types, new_errors = read_ned_declared_types({change.path: change.get_new_text() or "" for change in changes if change.status != "removed"}, omnetpp_project, new_packages)
    for change in changes:
        selection.begin_file(change, "ned")
        path = change.path
        if path in new_errors:
            selection.add_all("N4", path, f"the NED file does not load: {new_errors[path]}")
        elif path in new_packages:
            expected = get_expected_ned_package(path, project.ned_folders, change.new_side)
            if expected is not None and new_packages[path] != expected:
                selection.add_all("N4", path, f"the declared package {new_packages[path]!r} is not the expected package {expected!r}")
        entry = test_map.get(path) or {}
        bits = 0
        for run_set in entry.get("types", {}).values():
            bits |= test_map.bits(run_set)
        selection.add(bits, "N1", path, "a type of the file changed")
        before = old_types.get(path, set())
        after = new_types.get(path, set())
        added = after - before
        simple_names = {qname.rsplit(".", 1)[-1] for qname in added}
        if os.path.basename(path) == "package.ned":
            # the package of each file below the folder can change
            folder = os.path.dirname(path)
            if folder in project.ned_folders and _read_ned_package(change.get_old_text()) != _read_ned_package(change.get_new_text()):
                selection.add_all("N4", path, "the root package of a NED folder changed, so the other files do not declare the expected package")
            bits = 0
            for other_path, content in test_map.get_all_files().items():
                if other_path.endswith(".ned") and (folder == "" or other_path.startswith(folder + "/")):
                    for qname, run_set in (content or {}).get("types", {}).items():
                        bits |= test_map.bits(run_set)
                        simple_names.add(qname.rsplit(".", 1)[-1])
            selection.add(bits, "N3", path, "a type of the package changed")
        if simple_names:
            bits = 0
            for qname, type_bits in test_map.get_ned_types().items():
                if qname.rsplit(".", 1)[-1] in simple_names:
                    bits |= type_bits
            selection.add(bits, "N2", path, "a type with the same simple name as a new type: " + ", ".join(sorted(simple_names)[:5]))
        if added:
            _check_ned_duplicates(selection, change, added, project)
        _select_data(selection, change)
        selection.end_file()

def _check_ned_duplicates(selection, change, added, project):
    # rule N4: a new type that another NED file also declares stops the loading of all NED files
    side = change.new_side
    candidates = set()
    for simple_name in {qname.rsplit(".", 1)[-1] for qname in added}:
        candidates.update(file for file in side.grep(_NED_DECLARATION.format(re.escape(simple_name)), project.ned_folders) if file != change.path)
    if not candidates:
        return
    types, _ = read_ned_declared_types({file: side.read(file) or "" for file in sorted(candidates)}, project.simulation_project.get_omnetpp_project())
    for file, qnames in types.items():
        duplicates = qnames & added
        if duplicates:
            selection.add_all("N4", change.path, f"{', '.join(sorted(duplicates))} is also declared in {file}")

def _select_ini(selection, change, project):
    test_map = selection.test_map
    path = change.path
    entry = test_map.get(path) or {}
    main_bits = test_map.get_ini_file_runs(path)
    old_sections, _ = read_ini_sections(change.get_old_text() or "")
    new_sections, new_error = read_ini_sections(change.get_new_text() or "")
    if change.status == "removed" or new_error:
        selection.add(main_bits, "I3", path, "the file is removed" if change.status == "removed" else f"the file does not parse: {new_error}")
    else:
        changed = [name for name in sorted(set(old_sections) | set(new_sections)) if old_sections.get(name) != new_sections.get(name)]
        iteration = []
        for name in changed:
            before = collections.Counter(old_sections.get(name, []))
            after = collections.Counter(new_sections.get(name, []))
            if any(_is_iteration_entry(item) for item in (before - after) + (after - before)):
                iteration.append(name)
        if iteration:
            selection.add(main_bits, "I3", path, "the runs of a config can change: " + ", ".join(iteration[:3]))
        else:
            for name in changed:
                selection.add(test_map.bits(entry.get("sections", {}).get(name)), "I1", path, name)
    # rule I2 (v1): the runs that include the file read it as data
    data_bits = 0
    for run_set in entry.get("data", {}).values():
        data_bits |= test_map.bits(run_set)
    selection.add(data_bits & ~main_bits, "I2", path, "an ini file that the run includes")

def _select_data(selection, change, include_file=True):
    # rules F1 and F2
    test_map = selection.test_map
    path = change.path
    if include_file:
        bits = 0
        for run_set in (test_map.get(path) or {}).get("data", {}).values():
            bits |= test_map.bits(run_set)
        selection.add(bits, "F1", path, "the run used the file")
    if change.status != "modified":
        folder = os.path.dirname(path)
        while True:
            bits = 0
            for run_set in (test_map.get(folder) or {}).get("data", {}).values() if folder else []:
                bits |= test_map.bits(run_set)
            selection.add(bits, "F1", folder, f"the run looked up the folder of a {change.status} file")
            index = test_map.get_index(folder) or {}
            selection.add(test_map.bits(index.get("listed")), "F2", folder or ".", f"the run listed the folder of a {change.status} file")
            if not folder:
                break
            folder = os.path.dirname(folder)

def _select_store(selection, change, project, kind):
    # rule E1: the tests whose stored entry changed
    if kind != "fingerprint":
        selection.add_kind(kind, "E4", change.path, "the expected results changed")
        return
    try:
        old_entries = json.loads(change.get_old_text() or "[]")
        new_entries = json.loads(change.get_new_text() or "[]")
    except ValueError as e:
        selection.add_kind(kind, "E1", change.path, f"the store does not parse: {e}")
        return
    old_keys = get_fingerprint_store_test_keys(old_entries)
    for key, entry in get_fingerprint_store_test_keys(new_entries).items():
        if old_keys.get(key) != entry:
            selection.add_test(kind, key, "E1", change.path, "a new entry" if key not in old_keys else "the entry changed")

def _select_opp(selection, change, project):
    # rules R11 and E5: a field of the project changed
    try:
        before = _read_opp_fields(change.get_old_text()) if change.get_old_text() else {}
        after = _read_opp_fields(change.get_new_text()) if change.get_new_text() else {}
    except (ValueError, SyntaxError) as e:
        selection.add_all("R11", change.path, f"the file does not parse: {e}")
        return
    if before.get("name", project.name) != project.name and after.get("name", project.name) != project.name:
        return
    changed = {name for name in set(before) | set(after) if before.get(name) != after.get(name)}
    others = changed - HARMLESS_PROJECT_FIELDS - {"test_parameters"}
    if others:
        selection.add_all("R11", change.path, "changed fields: " + ", ".join(sorted(others)))
    if "test_parameters" in changed:
        before_parameters = before.get("test_parameters") or {}
        after_parameters = after.get("test_parameters") or {}
        for kind in sorted(set(before_parameters) | set(after_parameters)):
            if kind not in NON_TEST_KINDS and before_parameters.get(kind) != after_parameters.get(kind):
                if not _select_baseline_pin(selection, change, project, kind, before_parameters.get(kind) or {}, after_parameters.get(kind) or {}):
                    selection.add_kind(kind, "E5", change.path, f"the test parameters of {kind} changed")

# the baseline file of a statistical test: <working directory>/<ini file>-<config>-#<run>.sca
_STATISTICAL_BASELINE_FILE = re.compile(r"(.*\.ini)-(.*)-#(\d+)\.sca")

def _select_baseline_pin(selection, change, project, kind, before, after):
    # rule E2: only the pin of the statistical baseline moved; returns False if the rule does not apply
    old_baseline, new_baseline = before.get("baseline") or {}, after.get("baseline") or {}
    if kind != "statistical" or not old_baseline.get("ref") or not new_baseline.get("ref"):
        return False
    def without(parameters, name):
        return {key: value for key, value in parameters.items() if key != name}
    if without(before, "baseline") != without(after, "baseline") or without(old_baseline, "ref") != without(new_baseline, "ref"):
        return False
    old_ref, new_ref = old_baseline["ref"], new_baseline["ref"]
    folder = os.path.join(project.root_folder, new_baseline.get("folder", "."))
    if not os.path.isdir(folder) or not is_commit(folder, old_ref) or not is_commit(folder, new_ref):
        selection.add_kind(kind, "E2", change.path, f"the baseline pin moved from {old_ref[:10]} to {new_ref[:10]}, and the checkout {new_baseline.get('folder')} does not have both commits")
        return True
    names = _git(folder, "-c", "core.quotePath=false", "diff", "--name-only", "--no-renames", old_ref, new_ref, "--").stdout.splitlines()
    # the key of a test without its sim time limit -> the changed baseline file
    changed = {}
    for name in names:
        match = _STATISTICAL_BASELINE_FILE.fullmatch(os.path.basename(name))
        if match:
            ini_path = os.path.normpath(os.path.join(os.path.dirname(name), match.group(1)))
            changed[f"{kind}:{ini_path}:{match.group(2)}:#{match.group(3)}:"] = name
    # the rule shows for the file also when no test of the map has a changed baseline file
    selection._note("E2")
    for key in selection.test_map.tests.get(kind, {}):
        name = changed.get(key[:key.rindex(":") + 1])
        if name:
            selection.add_test(kind, key, "E2", change.path, f"the baseline file {name} changed")
    return True

def select_side(test_map, project, file_changes, side):
    """Applies the rules of section 5 of the plan to the changes of one diff, and returns a :py:class:`SideSelection`."""
    selection = SideSelection(test_map, side)
    changed_headers = {}
    ned_changes = []
    for change in file_changes:
        input_class = project.classify(change.path)
        if input_class == "ned":
            ned_changes.append(change)
            continue
        selection.begin_file(change, input_class)
        _select_release_only_includes(selection, change)
        if input_class == "build":
            selection.add_all("R11", change.path, "a build file")
        elif input_class == "opp":
            _select_opp(selection, change, project)
        elif input_class == "store":
            _select_store(selection, change, project, project.stores[change.path])
        elif input_class == "cpp":
            _select_cpp(selection, change, project, changed_headers)
        elif input_class == "msg":
            if change.status != "modified":
                selection.add_all("R7", change.path, f"a message file is {change.status}, so a translation unit is too")
            else:
                # rule R10 (v1): the generated files change
                changed_headers[os.path.splitext(change.path)[0] + "_m.h"] = "R10"
        elif input_class == "ini":
            _select_ini(selection, change, project)
        _select_data(selection, change, include_file=input_class != "ini")
        selection.end_file()
    if ned_changes:
        _select_ned(selection, ned_changes, project)
    if changed_headers:
        _select_changed_headers(selection, changed_headers)
        for path, status, input_class, rules in selection.files:
            rule = changed_headers.get(path) or changed_headers.get(os.path.splitext(path)[0] + "_m.h") if input_class == "msg" else changed_headers.get(path)
            if rule:
                rules.setdefault(rule, {"runs": 0, "tests": 0, "all": False, "kinds": set()})["headers"] = True
    return selection

#
# the environment
#

def _get_changed_harness_files(folder, commit):
    """Returns the files of a git checkout that differ from *commit* and can change the outcome of a test, or None if the commit is unknown."""
    if not commit or not is_commit(folder, commit):
        return None
    top_folder = _git(folder, "rev-parse", "--show-toplevel").stdout.strip()
    changed = set(_git(top_folder, "diff", "--name-only", commit, "--").stdout.split())
    changed.update(line[3:] for line in _git(top_folder, "status", "--porcelain", "--untracked-files=normal").stdout.splitlines() if line.startswith("?? "))
    return sorted(path for path in changed if not HARMLESS_HARNESS_FILES.search(path))

def get_environment_differences(test_map, simulation_project):
    """Returns the differences between the environment of the map and this one (section 4.3 of the plan): each one selects all tests."""
    from opp_repl.test.test_map.writer import get_test_map_header
    header = test_map.header
    current = get_test_map_header(simulation_project)
    differences = []
    if header.get("changed_files"):
        differences.append(Reason("4.3", None, "the map comes from a tree with changes", None))
    opp_repl_folder = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if header.get("opp_repl_changed_files"):
        differences.append(Reason("H1", None, "the map comes from an opp_repl with changes", None))
    elif header.get("opp_repl_version") != current.get("opp_repl_version"):
        changed = _get_changed_harness_files(opp_repl_folder, header.get("opp_repl_version"))
        if changed is None:
            differences.append(Reason("H1", None, f"the opp_repl commit of the map, {header.get('opp_repl_version')}, is not in this opp_repl repository", None))
        elif changed:
            differences.append(Reason("H1", None, f"opp_repl differs from the map: {', '.join(changed[:5])}" + (f" and {len(changed) - 5} more files" if len(changed) > 5 else ""), None))
    omnetpp_project = simulation_project.get_omnetpp_project()
    if header.get("omnetpp_commit") != current.get("omnetpp_commit") and omnetpp_project.has_root_path():
        changed = _get_changed_harness_files(omnetpp_project.get_root_path(), header.get("omnetpp_commit"))
        if changed is None:
            differences.append(Reason("H5", None, f"the omnetpp commit of the map, {header.get('omnetpp_commit')}, is not in this omnetpp repository", None))
        elif changed:
            differences.append(Reason("H5", None, f"omnetpp differs from the map: {', '.join(changed[:5])}" + (f" and {len(changed) - 5} more files" if len(changed) > 5 else ""), None))
    if header.get("compiler") != current.get("compiler"):
        differences.append(Reason("4.3", None, f"the compiler differs from the map: {current.get('compiler')} instead of {header.get('compiler')}", None))
    if header.get("enabled_features") != current.get("enabled_features"):
        before = set(header.get("enabled_features") or [])
        after = set(current.get("enabled_features") or [])
        differences.append(Reason("4.3", None, f"the features differ from the map: enabled {sorted(after - before)[:5]}, disabled {sorted(before - after)[:5]}", None))
    return differences

#
# the selection
#

class KindSelection:
    """The selection of one kind of test."""
    def __init__(self, kind, tests=None, everything=None):
        self.kind = kind
        self.tests = tests # the test keys at C, or None if they are not known
        self.everything = everything # the reason if all tests are selected
        self.selected = {} # test key -> reasons, for the tests of the map

class TestSelection:
    """
    The result of :py:func:`select_tests`: for each kind of test, the selected tests and the reasons.
    A test is selected if the rules select it, if all tests of its kind are selected, or if the map
    does not know it.
    """
    def __init__(self, test_map, changes, map_folder, sides, environment, kinds):
        self.test_map = test_map
        self.changes = changes
        self.map_folder = map_folder
        self.sides = sides
        self.environment = environment
        self.kinds = kinds

    def get_kind(self, kind):
        return self.kinds.get(kind) or KindSelection(kind, everything=Reason("4.3", None, f"the map has no {kind} tests", None))

    def get_reasons(self, kind, key):
        """Returns the reasons why a test is selected; an empty list if it is not selected."""
        kind_selection = self.get_kind(kind)
        if kind_selection.everything:
            return [kind_selection.everything]
        if key not in self.test_map.tests.get(kind, {}):
            return [Reason("4.3", None, "the test is not in the map", None)]
        return kind_selection.selected.get(key, [])

    def is_selected(self, kind, key):
        return bool(self.get_reasons(kind, key))

    def get_selected_tests(self, kind):
        """Returns the selected test keys at C, or None if the tests at C are not known."""
        kind_selection = self.get_kind(kind)
        if kind_selection.tests is None:
            return None
        return [key for key in kind_selection.tests if self.is_selected(kind, key)]

    def to_dict(self):
        result = {"map": self.map_folder, "map_commit": self.test_map.header.get("commit"), "changes": self.changes.describe(),
                  "environment": [str(reason) for reason in self.environment], "kinds": {}}
        for kind, kind_selection in self.kinds.items():
            selected = self.get_selected_tests(kind)
            result["kinds"][kind] = {"all": str(kind_selection.everything) if kind_selection.everything else None,
                                     "tests": len(kind_selection.tests) if kind_selection.tests is not None else None,
                                     "selected": {key: [str(reason) for reason in self.get_reasons(kind, key)] for key in (selected or [])}}
        return result

def _get_test_universe(kind, project, target_side):
    # the tests of a kind at C
    if kind == "fingerprint":
        parameters = project.test_parameters.get("fingerprint", {})
        store = parameters.get("store")
        if not store:
            return None
        text = target_side.read(os.path.normpath(store))
        if text is None:
            return []
        try:
            entries = json.loads(text)
        except ValueError:
            return None
        return list(get_fingerprint_store_test_keys(entries, parameters.get("defaults", {}).get("ingredients_list")))
    return None

def select_tests(simulation_project=None, changes=WORKTREE, map_folder=None, kinds=None, ignore_environment=False):
    """
    Selects the tests whose outcome a change can change.

    Parameters:
        simulation_project (:py:class:`SimulationProject <opp_repl.simulation.project.SimulationProject>` or None):
            The project. Default: the default project.

        changes (string):
            The change, see :py:class:`opp_repl.test.test_map.changes.Changes`. Default: ``worktree``,
            the working tree against ``HEAD``.

        map_folder (string or None):
            The folder of the test map. Default: ``coverage/test-map/map`` in the project root.

        kinds (list of strings or None):
            The kinds of test. Default: the kinds of the map.

        ignore_environment (bool):
            If true, a difference between the environment of the map and this one (the omnetpp and
            opp_repl commits, the compiler, the features) gives a warning instead of selecting all tests.

    Returns (:py:class:`TestSelection`):
        the selected tests of each kind, with the reasons.
    """
    from opp_repl.simulation.project import get_default_simulation_project
    if simulation_project is None:
        simulation_project = get_default_simulation_project()
    project = ProjectInfo(simulation_project)
    map_folder = os.path.abspath(map_folder or get_default_test_map_folder(simulation_project, "map"))
    test_map = TestMap(map_folder)
    root_folder = project.root_folder
    if not isinstance(changes, Changes):
        changes = Changes(root_folder, changes)
    map_commit = test_map.header.get("commit")
    if not map_commit or not is_commit(root_folder, map_commit):
        raise Exception(f"The map commit {map_commit} is not in the repository of {root_folder}; fetch it first")
    if _git(root_folder, "merge-base", "--is-ancestor", map_commit, changes.base, check=False).returncode != 0:
        _logger.warning(f"The map commit {map_commit[:10]} is not an ancestor of the base {changes.base[:10]}, so the selection can be wide")
    sides = []
    if changes.base != map_commit:
        sides.append(select_side(test_map, project, get_file_changes(root_folder, map_commit, changes.base), "A..B"))
    if changes.target != changes.base:
        sides.append(select_side(test_map, project, get_file_changes(root_folder, map_commit, changes.target), "A..C"))
    if test_map.get_release_only_blocks() is None:
        _logger.warning(f"The test map has version {test_map.header.get('version')} and does not list the release-only blocks, so rule R-NDEBUG does not apply")
    environment = get_environment_differences(test_map, simulation_project)
    if ignore_environment:
        for reason in environment:
            _logger.warning(f"Ignored: {reason.detail}")
    kinds = kinds or sorted(test_map.tests)
    target_side = Side(root_folder, changes.target)
    abnormal = test_map.get_abnormal_runs()
    entries = [(bits, reason) for side in sides for bits, reason in side.entries]
    if abnormal:
        entries.append((abnormal, Reason("4.3", None, "the run of the map did not end normally", None)))
    everything = [reason for side in sides for reason in side.everything] + ([] if ignore_environment else environment)
    def get_run_reasons(line_sensitive):
        run_reasons = collections.defaultdict(list)
        for bits, reason in entries:
            if reason.rule == "R3" and not line_sensitive:
                continue
            index = 0
            while bits:
                if bits & 1:
                    reasons = run_reasons[index]
                    if len(reasons) < MAX_REASONS:
                        reasons.append(reason)
                bits >>= 1
                index += 1
        return run_reasons
    result = {}
    for kind in kinds:
        run_reasons = get_run_reasons(kind in LINE_SENSITIVE_KINDS)
        always = [re.compile(pattern) for pattern in project.test_parameters.get(kind, {}).get("test_selection", {}).get("always", [])]
        kind_reasons = [side.kinds[kind] for side in sides if kind in side.kinds]
        kind_selection = KindSelection(kind, tests=_get_test_universe(kind, project, target_side),
                                       everything=(everything or kind_reasons or [None])[0])
        if kind not in test_map.tests:
            kind_selection.everything = kind_selection.everything or Reason("4.3", None, f"the map has no {kind} tests", None)
        if not kind_selection.everything:
            for index, reasons in run_reasons.items():
                for test_kind, key in test_map.run_tests.get(index, []):
                    if test_kind == kind:
                        kind_selection.selected.setdefault(key, []).extend(reasons)
            for side in sides:
                for test_kind, key, reason in side.tests:
                    if test_kind == kind:
                        kind_selection.selected.setdefault(key, []).append(reason)
            for key in test_map.tests.get(kind, {}):
                for pattern in always:
                    if pattern.search(key):
                        kind_selection.selected.setdefault(key, []).append(Reason("4.3", None, "the project selects this test always", None))
                        break
        result[kind] = kind_selection
    return TestSelection(test_map, changes, map_folder, sides, environment, result)

def print_test_selection(test_selection, explain=False, list_tests=True, output_stream=sys.stdout):
    """Prints the changed files and their rules, and the selected tests of each kind; with *explain*, also the reasons of each test."""
    test_map = test_selection.test_map
    print(f"Map: {test_selection.map_folder} ({test_map.header.get('project')} {str(test_map.header.get('commit'))[:10]}, {test_map.header.get('date')})", file=output_stream)
    print(f"Changes: {test_selection.changes.describe()}", file=output_stream)
    for reason in test_selection.environment:
        print(f"Environment: {reason.rule} {reason.detail}", file=output_stream)
    for side in test_selection.sides:
        print(f"Changed files {side.side}: {len(side.files)}" + (f"; the changed headers select {side.header_bits.bit_count()} runs" if side.header_bits else ""), file=output_stream)
        if explain:
            for path, status, input_class, rules in side.files:
                parts = [f"{rule} {_describe_note(note)}" + (" (only the tests that compare a text output)" if rule == "R3" else "") for rule, note in rules.items()]
                print(f"  {path} ({status}, {input_class}): {', '.join(parts) or 'no tests'}", file=output_stream)
    for kind, kind_selection in test_selection.kinds.items():
        selected = test_selection.get_selected_tests(kind)
        total = len(kind_selection.tests) if kind_selection.tests is not None else None
        if kind_selection.everything:
            print(f"{kind}: all tests are selected: {kind_selection.everything}", file=output_stream)
        else:
            print(f"{kind}: selected {len(selected) if selected is not None else len(kind_selection.selected)} of {total if total is not None else '?'} tests", file=output_stream)
            if list_tests:
                for key in (selected if selected is not None else sorted(kind_selection.selected)):
                    print(f"  {key}", file=output_stream)
                    if explain:
                        for reason in test_selection.get_reasons(kind, key):
                            print(f"      {reason}", file=output_stream)

#
# the test tasks
#

def get_test_kind(multiple_test_tasks):
    """Returns the kind of the tests of a task list of a run command, for example ``statistical`` for the list ``statistical test``."""
    from opp_repl.test.fingerprint.task import MultipleFingerprintTestTasks
    if isinstance(multiple_test_tasks, MultipleFingerprintTestTasks):
        return "fingerprint"
    name = multiple_test_tasks.name
    return name[:-len(" test")] if name.endswith(" test") else name

def get_test_key(kind, test_task):
    """Returns the key of a test task of *kind* in ``tests.json`` of the map: the key of its run, and for a fingerprint test also its ingredients."""
    from opp_repl.test.test_map.record import get_test_map_run_key
    run_key = get_test_map_run_key(kind, test_task.simulation_task)
    return run_key + ":" + test_task.ingredients if kind == "fingerprint" else run_key

def get_fingerprint_test_key(fingerprint_test_task):
    """Returns the key of a fingerprint test task in ``tests.json`` of the map."""
    return get_test_key("fingerprint", fingerprint_test_task)

def select_fingerprint_test_tasks(multiple_fingerprint_test_tasks, test_selection):
    """
    Keeps only the selected tests of a :py:class:`MultipleFingerprintTestTasks
    <opp_repl.test.fingerprint.task.MultipleFingerprintTestTasks>`: a group of ingredients keeps its
    selected ingredients. Returns the number of selected tests and the number of all tests.
    """
    from opp_repl.test.fingerprint.task import FingerprintTestGroupTask
    groups = []
    selected = total = 0
    for group in multiple_fingerprint_test_tasks.tasks:
        tasks = [task for task in group.tasks if test_selection.is_selected("fingerprint", get_fingerprint_test_key(task))]
        total += len(group.tasks)
        selected += len(tasks)
        if len(tasks) == len(group.tasks):
            groups.append(group)
        elif tasks:
            groups.append(FingerprintTestGroupTask(sim_time_limit=group.sim_time_limit, tasks=tasks))
    multiple_fingerprint_test_tasks.tasks = groups
    return selected, total

def get_test_selection_for_run(simulation_project, changes, test_map=None, ignore_environment=False, kinds=None):
    """Returns the :py:class:`TestSelection` for the ``changes`` option of a run command, and logs what the selection includes."""
    test_selection = select_tests(simulation_project=simulation_project, changes=changes, map_folder=test_map, kinds=kinds, ignore_environment=ignore_environment)
    if test_selection.changes.is_target_dirty():
        _logger.warning(f"The working tree has changes that the changes {changes} do not include; the tests run with them")
    for reason in test_selection.environment:
        if not ignore_environment:
            _logger.warning(f"All tests are selected: {reason.detail}")
    return test_selection

def select_test_tasks(kind, multiple_test_tasks, test_selection):
    """
    Keeps only the tests of *multiple_test_tasks* that *test_selection* selects. A kind of test that
    the map does not hold keeps all its tests.
    """
    if kind == "fingerprint":
        selected, total = select_fingerprint_test_tasks(multiple_test_tasks, test_selection)
    else:
        tasks = [task for task in multiple_test_tasks.tasks if test_selection.is_selected(kind, get_test_key(kind, task))]
        selected, total = len(tasks), len(multiple_test_tasks.tasks)
        multiple_test_tasks.tasks = tasks
    everything = test_selection.get_kind(kind).everything
    _logger.info(f"Selected {selected} of {total} {kind} tests for the changes {test_selection.changes.describe()}" + (f": {everything}" if everything else ""))
    return multiple_test_tasks

def apply_test_map_options(kind, multiple_test_tasks, kwargs, test_map_records=None, changes=None, test_map=None, ignore_environment=False):
    """
    Applies the options of the test map to the tasks of a run command of *kind*, and returns the
    keyword arguments for the run of the tasks. With *changes*, only the selected tests stay (see
    :py:func:`select_tests`). With *test_map_records*, each run writes its record into this folder
    (see :py:mod:`opp_repl.test.test_map.record`); the records need all tests and the coverage build.
    """
    if changes:
        if test_map_records:
            raise Exception("The records of the test map need all tests, so they cannot run with a selection of changes")
        test_selection = get_test_selection_for_run(kwargs["simulation_project"], changes, test_map=test_map, ignore_environment=ignore_environment, kinds=[kind])
        select_test_tasks(kind, multiple_test_tasks, test_selection)
    if test_map_records:
        if kwargs.get("mode") != "coverage":
            raise Exception("The records of the test map need the coverage build (mode coverage)")
        from opp_repl.test.test_map.record import get_test_map_simulation_runner_class
        kwargs = dict(kwargs, simulation_runner_class=get_test_map_simulation_runner_class(test_map_records, kind))
    return kwargs
