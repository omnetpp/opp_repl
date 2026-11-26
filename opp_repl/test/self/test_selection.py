#!/usr/bin/env python3
"""
Tests the change-based test selection: the C++ tokens and the trivial hunks, the ini sections, the
diff reader and the change syntax on a git repository, the expected NED package, and the rules of the
selection on a small map in a git repository.
"""

import json
import os
import subprocess
import tempfile
import types
import unittest

from opp_repl.test.test_map.changes import *
from opp_repl.test.test_map.ndebug import *
from opp_repl.test.test_map.select import *
from opp_repl.test.test_map.select import _is_inside

def git(folder, *args):
    return subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True, check=True).stdout.strip()

def make_repository(folder, files):
    git(folder, "init", "-q")
    git(folder, "config", "user.email", "test@example.com")
    git(folder, "config", "user.name", "test")
    write_files(folder, files)
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "first")
    return git(folder, "rev-parse", "HEAD")

def write_files(folder, files):
    for path, text in files.items():
        full_path = os.path.join(folder, path)
        if text is None:
            os.remove(full_path)
            continue
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(text)

class TokenTestCase(unittest.TestCase):
    def test_comments_and_white_space_are_left_out(self):
        tokens = tokenize_cpp_lines("int a = 1; // one\n/* two\n three */ int  b=2;\n")
        self.assertEqual(tokens[0], ["int", "a", "=", "1", ";"])
        self.assertEqual(tokens[1], [])
        self.assertEqual(tokens[2], ["int", "b", "=", "2", ";"])

    def test_literals_keep_their_text(self):
        tokens = tokenize_cpp_lines('s = "a // b"; c = \'x\'; r = R"x(a\nb)x"; n = 1\'000;\n')
        self.assertIn('"a // b"', tokens[0])
        self.assertIn("'x'", tokens[0])
        self.assertIn('R"x(a\nb)x"', tokens[0])
        self.assertIn("1'000", tokens[1])

    def test_white_space_between_punctuation_is_a_token(self):
        self.assertNotEqual(tokenize_cpp_lines("a + +b;")[0], tokenize_cpp_lines("a ++b;")[0])
        self.assertEqual(tokenize_cpp_lines("a+b;")[0], tokenize_cpp_lines("a + b;")[0])

    def test_directives_keep_white_space_and_end(self):
        self.assertNotEqual(tokenize_cpp_lines("#define F(x) x\n")[0], tokenize_cpp_lines("#define F (x) x\n")[0])
        self.assertEqual(tokenize_cpp_lines("#include \"a.h\"\n")[0][-1], "<eod>")

    def test_a_splice_continues_a_comment(self):
        tokens = tokenize_cpp_lines("// a \\\nint x;\nint y;\n")
        self.assertEqual(tokens[1], [])
        self.assertEqual(tokens[2], ["int", "y", ";"])

class TrivialHunkTestCase(unittest.TestCase):
    def trivial(self, old, new, hunks):
        return get_trivial_hunks(tokenize_cpp_lines(old), tokenize_cpp_lines(new), hunks)

    def test_a_changed_comment_is_trivial(self):
        self.assertEqual(self.trivial("int a;\n// x\nint b;\n", "int a;\n// y\nint b;\n", [(2, 1, 2, 1)]), [True])

    def test_a_changed_statement_is_not_trivial(self):
        self.assertEqual(self.trivial("int a;\nint b;\n", "int a;\nint c;\n", [(2, 1, 2, 1)]), [False])

    def test_a_new_comment_line_is_trivial(self):
        self.assertEqual(self.trivial("int a;\nint b;\n", "int a;\n// new\nint b;\n", [(1, 0, 2, 1)]), [True])

    def test_an_opened_comment_makes_all_hunks_not_trivial(self):
        # the new "/*" hides the line below the hunk
        self.assertEqual(self.trivial("// x\nint a;\n// y */\n", "/* x\nint a;\n// y */\n", [(1, 1, 1, 1)]), [False])

class InsideTestCase(unittest.TestCase):
    def test_lines_of_the_body(self):
        self.assertTrue(_is_inside([10, 20], 11, 2))
        self.assertFalse(_is_inside([10, 20], 10, 1)) # the line of the opening brace
        self.assertFalse(_is_inside([10, 20], 19, 2)) # the line of the closing brace
        self.assertTrue(_is_inside([10, 20], 10, 0)) # new lines after the opening brace
        self.assertFalse(_is_inside([10, 20], 20, 0)) # new lines after the closing brace

class IniTestCase(unittest.TestCase):
    def test_sections_and_entries(self):
        sections, error = read_ini_sections('a = 1\n[General]\nb = "x # y" # comment\n[Config Foo]\nextends = Bar\ninclude other.ini\n[Bar]\nc = 1 \\\n  + 2\n')
        self.assertIsNone(error)
        self.assertEqual(sections["General"], [("a", "1"), ("b", '"x # y"')])
        self.assertEqual(sections["Config Foo"], [("extends", "Bar"), ("include", "other.ini")])
        self.assertEqual(sections["Config Bar"], [("c", "1   + 2")])

    def test_a_line_that_is_not_an_entry_is_an_error(self):
        self.assertIsNotNone(read_ini_sections("[General]\nnot an entry\n")[1])

    def test_the_keys_of_opp_repl_in_comments_are_entries(self):
        sections, error = read_ini_sections('[Config A]\n#expected-result = "ERROR"\n# a comment\n#abstract = true\nx = 1\n')
        self.assertIsNone(error)
        self.assertEqual(sections["Config A"], [("#expected-result", '"ERROR"'), ("#abstract", "true"), ("x", "1")])

class DiffTestCase(unittest.TestCase):
    def test_parse_diff(self):
        text = "\n".join(["diff --git a/x.cc b/x.cc", "index 1..2 100644", "--- a/x.cc", "+++ b/x.cc", "@@ -3,2 +3 @@",
                          "--- a/looks like a header", "-b", "+c",
                          "diff --git a/new file.txt b/new file.txt", "new file mode 100644", "--- /dev/null", "+++ b/new file.txt", "@@ -0,0 +1 @@", "+x",
                          "diff --git a/img.png b/img.png", "deleted file mode 100644", "Binary files a/img.png and /dev/null differ", ""])
        changes = parse_diff(text, None, None)
        self.assertEqual([(change.path, change.status, change.hunks) for change in changes],
                         [("x.cc", "modified", [(3, 2, 3, 1)]), ("new file.txt", "added", [(0, 0, 1, 1)]), ("img.png", "removed", None)])

    def test_changes_of_a_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            first = make_repository(folder, {"a.txt": "1\n2\n3\n", "b.txt": "b\n"})
            write_files(folder, {"a.txt": "1\nx\n3\n", "b.txt": None})
            git(folder, "commit", "-q", "-am", "second")
            second = git(folder, "rev-parse", "HEAD")
            write_files(folder, {"c.txt": "new\n"})
            self.assertEqual(Changes(folder, second).base, first)
            self.assertEqual(Changes(folder, "HEAD~1..HEAD").target, second)
            self.assertEqual(Changes(folder, "HEAD...worktree").target, WORKTREE)
            changes = {change.path: change for change in get_file_changes(folder, first, WORKTREE)}
            self.assertEqual({path: change.status for path, change in changes.items()}, {"a.txt": "modified", "b.txt": "removed", "c.txt": "added"})
            self.assertEqual(changes["a.txt"].hunks, [(2, 1, 2, 1)])
            self.assertEqual((changes["a.txt"].get_old_text(), changes["a.txt"].get_new_text()), ("1\n2\n3\n", "1\nx\n3\n"))
            with open(os.path.join(folder, "x.patch"), "w") as f:
                f.write(git(folder, "diff", "HEAD~1", "HEAD") + "\n")
            git(folder, "checkout", "-q", "HEAD~1")
            patch = Changes(folder, os.path.join(folder, "x.patch"))
            self.assertEqual(patch.base, first)
            self.assertEqual(Side(folder, patch.target).read("a.txt"), "1\nx\n3\n")
            self.assertEqual(git(folder, "status", "--porcelain", "--untracked-files=no"), "")

class ExpectedNedPackageTestCase(unittest.TestCase):
    def test_root_package_and_folders(self):
        side = types.SimpleNamespace(read=lambda path: {"examples/package.ned": "// x\npackage inet.examples;\n"}.get(path))
        self.assertEqual(get_expected_ned_package("examples/a/b/X.ned", ["src", "examples"], side), "inet.examples.a.b")
        self.assertEqual(get_expected_ned_package("src/inet/X.ned", ["src", "examples"], side), "inet")
        self.assertIsNone(get_expected_ned_package("other/X.ned", ["src", "examples"], side))

class FakeProject:
    def __init__(self, root_folder):
        self.root_folder = root_folder
        self.cpp_folders = ["src"]
        self.msg_folders = ["src"]
        self.ned_folders = ["src"]
        self.python_folders = ["python"]
        self.ci_files = ["^_scripts/ci/"]
        self.test_parameters = {"fingerprint": {"store": "store.json"}, "unit": {"defaults": {"test_folder": "tests/unit"}}}

    def get_name(self):
        return "fake"

    def get_full_path(self, path):
        return os.path.join(self.root_folder, path)

SOURCES = {
    "src/a.h": "#pragma once\nstruct A {\n    int x;\n    int get() {\n        return x;\n    }\n};\n",
    "src/a.cc": "#include \"a.h\"\n\nint f()\n{\n    return 1;\n}\n\nint g()\n{\n    return 2;\n}\n",
    "src/b.cc": "#include \"a.h\"\n\nint h()\n{\n    return 3;\n}\n",
    "examples/omnetpp.ini": "[General]\na = 1\n[Config One]\nb = 1\n[Config Two]\nb = 2\n",
    "examples/data.xml": "<x/>\n",
    "tests/unit/A.test": "%description: a test\n",
    "examples/results.anf": "<analysis/>\n",
    "python/x/plot.py": "x = 1\n",
    "tests/unit/Support.h": "#pragma once\n",
    "tests/unit/lib/L.cc": "int l() { return 0; }\n",
    "store.json": json.dumps([{"working_directory": "examples", "ini_file": "omnetpp.ini", "config": "One", "run_number": 0, "sim_time_limit": "1s",
                               "test_result": "PASS", "ingredients": "tplx", "fingerprint": "1111-1111", "timestamp": 1}]),
}

def run_entry(run_id, config, normal_end=True):
    return {"key": f"fingerprint:examples/omnetpp.ini:{config}:#0:1s", "kind": "fingerprint", "working_directory": "examples", "ini_file": "omnetpp.ini",
            "config": config, "run_number": 0, "sim_time_limit": "1s", "exit_code": 0, "end": None, "normal_end": normal_end,
            "sections": [f"Config {config}", "General"]}

MAP_FILES = {
    "header.json": {"version": 2, "project": "fake"},
    "runs.json": {"r1": run_entry("r1", "One"), "r2": run_entry("r2", "Two"), "r3": run_entry("r3", "Three", normal_end=False)},
    "tests.json": {"fingerprint": {f"fingerprint:examples/omnetpp.ini:{config}:#0:1s:tplx": [run_id] for run_id, config in [("r1", "One"), ("r2", "Two"), ("r3", "Three")]},
                   # the statistical tests share the runs here, which keeps the run sets of the other tests
                   "statistical": {f"statistical:examples/omnetpp.ini:{config}:#0:1s": [run_id] for run_id, config in [("r1", "One"), ("r2", "Two")]},
                   "unit": {"unit:tests/unit/A.test": ["r1"]},
                   "chart": {"chart:examples/results.anf:1": ["r1", "r2"]}},
    "src/a.h.json": {"functions": [{"lines": [4, 6], "name": "A::get()", "runs": ["r2"], "tus": ["src/b.cc"]}], "included_by": ["src/a.cc", "src/b.cc"]},
    "src/a.cc.json": {"functions": [{"lines": [4, 6], "name": "f()", "runs": ["r1"]}, {"lines": [9, 11], "name": "g()", "runs": "all"}], "tu_runs": "all"},
    "src/b.cc.json": {"functions": [{"lines": [4, 6], "name": "h()", "runs": ["r2"]}], "tu_runs": ["r2"]},
    "examples/omnetpp.ini.json": {"sections": {"Config One": ["r1"], "Config Two": ["r2"], "General": ["r1", "r2"]}, "data": {"read": ["r1", "r2"]}},
    "examples/data.xml.json": {"data": {"read": ["r2"]}},
    "tests/unit/Support.h.json": {"test_runs": ["r2"]},
    "examples/index.json": {"data": 2, "listed": ["r1"]},
}

class SelectionTestCase(unittest.TestCase):
    """The rules on a repository with two C++ files, a header, an ini file, a data file and a store, and a map of three runs."""
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.folder.name, "project")
        os.makedirs(self.root)
        self.map_commit = make_repository(self.root, SOURCES)
        self.map_folder = os.path.join(self.folder.name, "map")
        for path, content in MAP_FILES.items():
            full_path = os.path.join(self.map_folder, path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as f:
                json.dump(content, f)
        self.test_map = TestMap(self.map_folder)
        self.project = ProjectInfo(FakeProject(self.root))

    def tearDown(self):
        self.folder.cleanup()

    def select(self, files):
        write_files(self.root, files)
        selection = select_side(self.test_map, self.project, get_file_changes(self.root, self.map_commit, WORKTREE), "A..C")
        runs = 0
        for bits, reason in selection.entries:
            runs |= bits
        return {self.test_map.run_ids[index] for index in range(len(self.test_map.run_ids)) if runs >> index & 1}, selection

    def test_a_body_change_selects_the_runs_of_the_function(self):
        runs, selection = self.select({"src/a.cc": SOURCES["src/a.cc"].replace("return 1;", "return 5;")})
        self.assertEqual(runs, {"r1"})
        self.assertEqual([reason.rule for _, reason in selection.entries], ["R2"])

    def test_a_comment_selects_nothing(self):
        runs, selection = self.select({"src/a.cc": SOURCES["src/a.cc"].replace("return 1;", "return 1; // one")})
        self.assertEqual((runs, selection.everything), (set(), []))

    def test_a_line_shift_is_rule_R3(self):
        runs, selection = self.select({"src/a.cc": SOURCES["src/a.cc"].replace("int g()", "// new\nint g()")})
        self.assertEqual([reason.rule for _, reason in selection.entries], ["R3"])

    def test_a_change_outside_the_bodies_of_a_source_selects_all(self):
        runs, selection = self.select({"src/a.cc": "#include <vector>\n" + SOURCES["src/a.cc"]})
        self.assertEqual([reason.rule for reason in selection.everything], ["R6"])

    def test_a_header_change_selects_the_functions_whose_emitters_include_it(self):
        # all three functions of the map: each translation unit that emits them includes a.h
        runs, selection = self.select({"src/a.h": SOURCES["src/a.h"].replace("int x;", "int x;\n    int y;")})
        self.assertEqual(runs, {"r1", "r2", "r3"})
        self.assertIn("R4", [reason.rule for _, reason in selection.entries])

    def test_a_renamed_function_selects_the_runs_of_the_old_function(self):
        # rule R6 v2: the hunk is the signature line, outside the bodies, but holds only a function definition
        runs, selection = self.select({"src/a.cc": SOURCES["src/a.cc"].replace("int f()", "int f2()")})
        self.assertEqual((runs, selection.everything), ({"r1"}, []))

    def test_a_new_function_selects_nothing_by_itself(self):
        runs, selection = self.select({"src/a.cc": SOURCES["src/a.cc"].replace("\nint g()", "\nint k()\n{\n    return 3;\n}\n\nint g()")})
        # the new lines move g, which only the tests of a text output see (R3)
        self.assertEqual(({reason.rule for _, reason in selection.entries}, selection.everything), ({"R3"}, []))

    def test_a_new_global_variable_selects_all(self):
        runs, selection = self.select({"src/a.cc": SOURCES["src/a.cc"].replace("\nint g()", "\nint counter = 0;\n\nint g()")})
        self.assertEqual([reason.rule for reason in selection.everything], ["R6"])

    def test_a_new_source_selects_all(self):
        runs, selection = self.select({"src/c.cc": "int k() { return 0; }\n"})
        self.assertEqual([reason.rule for reason in selection.everything], ["R7"])

    def test_an_ini_section_selects_its_runs(self):
        runs, selection = self.select({"examples/omnetpp.ini": SOURCES["examples/omnetpp.ini"].replace("b = 2", "b = 3")})
        self.assertEqual(runs, {"r2"})

    def test_an_expected_result_comment_selects_the_runs_of_its_section(self):
        runs, selection = self.select({"examples/omnetpp.ini": SOURCES["examples/omnetpp.ini"].replace("b = 2", 'b = 2\n#expected-result = "ERROR"')})
        self.assertEqual(runs, {"r2"})

    def test_an_iteration_variable_selects_the_runs_of_the_file(self):
        runs, selection = self.select({"examples/omnetpp.ini": SOURCES["examples/omnetpp.ini"].replace("b = 2", "b = ${x=1,2}")})
        self.assertEqual(runs, {"r1", "r2", "r3"})

    def test_a_data_file_and_a_listed_folder(self):
        runs, _ = self.select({"examples/data.xml": "<y/>\n"})
        self.assertEqual(runs, {"r2"})
        runs, _ = self.select({"examples/data.xml": SOURCES["examples/data.xml"], "examples/new.xml": "<z/>\n"})
        self.assertEqual(runs, {"r1"})

    def test_a_changed_store_entry_selects_its_test(self):
        entries = json.loads(SOURCES["store.json"])
        entries[0]["fingerprint"] = "2222-2222"
        _, selection = self.select({"store.json": json.dumps(entries)})
        self.assertEqual([(kind, key) for kind, key, _ in selection.tests], [("fingerprint", "fingerprint:examples/omnetpp.ini:One:#0:1s:tplx")])

    def test_a_file_of_the_ci_jobs_selects_all(self):
        for path in (".github/workflows/tests.yml", "_scripts/ci/build.sh"):
            _, selection = self.select({path: "x\n"})
            self.assertEqual([reason.rule for reason in selection.everything], ["H6"])
            os.remove(os.path.join(self.root, path))

    def test_a_build_file_selects_all(self):
        _, selection = self.select({"src/makefrag": "X = 1\n"})
        self.assertEqual([reason.rule for reason in selection.everything], ["R11"])

    def test_a_changed_timestamp_selects_nothing(self):
        entries = json.loads(SOURCES["store.json"])
        entries[0]["timestamp"] = 2
        _, selection = self.select({"store.json": json.dumps(entries)})
        self.assertEqual(selection.tests, [])

    def make_statistics_pins(self):
        # a statistics repository with two pins, of which the second changes the result of config One,
        # and a .opp file in the map commit that pins the first
        statistics = os.path.join(self.root, "statistics")
        os.makedirs(statistics)
        files = {f"examples/omnetpp.ini-{config}-#0.sca": f"scalar x y {value}\n" for config, value in [("One", 1), ("Two", 2)]}
        old_ref = make_repository(statistics, files)
        write_files(statistics, {"examples/omnetpp.ini-One-#0.sca": "scalar x y 5\n"})
        git(statistics, "commit", "-q", "-a", "-m", "second")
        new_ref = git(statistics, "rev-parse", "HEAD")
        write_files(self.root, {".gitignore": "/statistics\n", "fake.opp": self.opp_text(old_ref)})
        git(self.root, "add", ".gitignore", "fake.opp")
        git(self.root, "commit", "-q", "-m", "pin")
        self.map_commit = git(self.root, "rev-parse", "HEAD")
        return old_ref, new_ref

    def opp_text(self, ref, mode="release"):
        parameters = {"statistical": {"defaults": {"mode": mode}, "baseline": {"repository": "x/statistics", "ref": ref, "folder": "statistics"}}}
        return f"SimulationProject(name=\"fake\", test_parameters={parameters!r})\n"

    def test_a_moved_statistics_pin_selects_the_tests_of_the_changed_results(self):
        old_ref, new_ref = self.make_statistics_pins()
        _, selection = self.select({"fake.opp": self.opp_text(new_ref)})
        self.assertEqual([(kind, key, reason.rule) for kind, key, reason in selection.tests], [("statistical", "statistical:examples/omnetpp.ini:One:#0:1s", "E2")])
        self.assertEqual(selection.kinds, {})

    def test_a_pin_that_the_checkout_does_not_have_selects_all_statistical_tests(self):
        self.make_statistics_pins()
        _, selection = self.select({"fake.opp": self.opp_text("0" * 40)})
        self.assertEqual({kind: reason.rule for kind, reason in selection.kinds.items()}, {"statistical": "E2"})

    def test_another_statistical_parameter_selects_all_statistical_tests(self):
        old_ref, new_ref = self.make_statistics_pins()
        _, selection = self.select({"fake.opp": self.opp_text(new_ref, mode="debug")})
        self.assertEqual({kind: reason.rule for kind, reason in selection.kinds.items()}, {"statistical": "E5"})

    def test_the_feature_tests_are_selected_by_the_class_of_the_file(self):
        _, selection = self.select({"src/a.cc": SOURCES["src/a.cc"].replace("return 1;", "return 5;")})
        self.assertEqual({kind: reason.rule for kind, reason in selection.kinds.items()}, {"feature": "V1", "validation": "V1"})
        _, selection = self.select({"src/a.cc": SOURCES["src/a.cc"], "examples/data.xml": "<y/>\n"})
        self.assertEqual(sorted(selection.kinds), ["feature", "validation"])
        # a file that no run used selects no feature test
        _, selection = self.select({"examples/data.xml": SOURCES["examples/data.xml"], "doc/notes.txt": "x\n"})
        self.assertEqual(selection.kinds, {})

    def test_the_file_of_an_opp_test_selects_the_test(self):
        _, selection = self.select({"tests/unit/A.test": SOURCES["tests/unit/A.test"] + "%activity: x\n"})
        self.assertEqual([(kind, key, reason.rule) for kind, key, reason in selection.tests], [("unit", "unit:tests/unit/A.test", "E6")])

    def test_a_file_that_the_own_code_of_a_test_includes_selects_the_test(self):
        runs, selection = self.select({"tests/unit/Support.h": "#pragma once\nint x;\n"})
        self.assertEqual(runs, {"r2"})

    def test_an_analysis_file_selects_its_chart_tests(self):
        _, selection = self.select({"examples/results.anf": "<analysis version='2'/>\n"})
        self.assertEqual([(kind, key, reason.rule) for kind, key, reason in selection.tests], [("chart", "chart:examples/results.anf:1", "H3")])

    def test_the_python_code_selects_all_chart_and_validation_tests(self):
        _, selection = self.select({"python/x/plot.py": "x = 2\n"})
        self.assertEqual({kind: reason.rule for kind, reason in selection.kinds.items()}, {"chart": "H2", "validation": "H2"})

    def test_the_opp_tests_at_the_target_also_hold_a_new_test(self):
        write_files(self.root, {"tests/unit/B.test": "%description: new\n", "tests/unit/work/C.test": "%description: scratch\n"})
        from opp_repl.test.test_map.select import _get_test_universe
        tests = _get_test_universe("unit", self.project, Side(self.root, WORKTREE))
        self.assertEqual(tests, ["unit:tests/unit/A.test", "unit:tests/unit/B.test"])

    def test_the_support_library_selects_all_tests_of_its_kind(self):
        _, selection = self.select({"tests/unit/lib/L.cc": "int l() { return 1; }\n"})
        self.assertEqual({kind: reason.rule for kind, reason in selection.kinds.items()}, {"unit": "H4"})

    def add_release_only_block(self, names=[], includes=[]):
        with open(os.path.join(self.map_folder, "release-only.json"), "w") as f:
            json.dump({"blocks": [{"path": "src/a.h", "lines": [2, 4], "names": names, "includes": includes, "inside_function": False, "runs": ["r1"]}]}, f)
        self.test_map = TestMap(self.map_folder)

    def test_a_function_that_a_release_only_block_names_also_selects_the_runs_of_the_block(self):
        self.add_release_only_block(names=["h"])
        runs, selection = self.select({"src/b.cc": SOURCES["src/b.cc"].replace("return 3;", "return 4;")})
        self.assertEqual(runs, {"r1", "r2"})
        self.assertEqual([reason.rule for _, reason in selection.entries], ["R2", "R-NDEBUG"])

    def test_a_file_that_a_release_only_block_includes_selects_the_runs_of_the_block(self):
        self.add_release_only_block(includes=["examples/data.xml"])
        runs, selection = self.select({"examples/data.xml": "<y/>\n"})
        self.assertEqual(runs, {"r1", "r2"})
        self.assertIn("R-NDEBUG", [reason.rule for _, reason in selection.entries])

class SmokeTestTimeLimitsTestCase(unittest.TestCase):
    """The bound of the smoke tests from the store of the simulation-time limits (decision D2c)."""
    def test_the_limits_of_a_config_with_and_without_a_value(self):
        from opp_repl.test.smoke import SMOKE_TEST_SAFETY_CPU_TIME_LIMIT, get_smoke_test_time_limits
        limits = {("examples", "omnetpp.ini", "Fast", 0): "0.5s", ("examples", "omnetpp.ini", "Short", 0): None}
        sim_time_limit, cpu_time_limit = get_smoke_test_time_limits(None, cpu_time_limit="1s", sim_time_limits=limits)
        def config(name, limit=None):
            return types.SimpleNamespace(working_directory="examples", ini_file="omnetpp.ini", config=name, sim_time_limit=limit)
        self.assertEqual((sim_time_limit(config("Fast"), 0), cpu_time_limit(config("Fast"), 0)), ("0.5s", SMOKE_TEST_SAFETY_CPU_TIME_LIMIT))
        # a run that ends by itself keeps the limit of its config
        self.assertEqual((sim_time_limit(config("Short", "10s"), 0), cpu_time_limit(config("Short"), 0)), ("10s", SMOKE_TEST_SAFETY_CPU_TIME_LIMIT))
        # a config without a value keeps the CPU-time limit
        self.assertEqual((sim_time_limit(config("Other"), 0), cpu_time_limit(config("Other"), 0)), (None, "1s"))
        self.assertEqual(get_smoke_test_time_limits(types.SimpleNamespace(test_parameters={}), cpu_time_limit="1s"), (None, "1s"))

class FindTestMapTestCase(unittest.TestCase):
    """The map for a base: the newest version of a map repository whose commit is an ancestor of the base, or the nearer local map."""
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.folder.name, "project")
        os.makedirs(self.root)
        self.commits = [make_repository(self.root, {"a.txt": "0\n"})]
        for index in range(1, 4):
            write_files(self.root, {"a.txt": f"{index}\n"})
            git(self.root, "commit", "-q", "-a", "-m", str(index))
            self.commits.append(git(self.root, "rev-parse", "HEAD"))
        # the map repository has the maps of the commits 0 and 2, and later one of a commit of another branch
        self.repository = os.path.join(self.folder.name, "coverage")
        os.makedirs(self.repository)
        make_repository(self.repository, {"map/header.json": json.dumps({"commit": self.commits[0]})})
        for commit in (self.commits[2], "f" * 40):
            write_files(self.repository, {"map/header.json": json.dumps({"commit": commit})})
            git(self.repository, "commit", "-q", "-a", "-m", "map")
        self.project = types.SimpleNamespace(test_parameters={"coverage": {"baseline": {"repository": "x/coverage", "folder": "../coverage"}}},
                                             get_full_path=lambda path: os.path.normpath(os.path.join(self.root, path)))

    def tearDown(self):
        self.folder.cleanup()

    def header_commit(self, folder):
        with open(os.path.join(folder, "header.json")) as f:
            return json.load(f)["commit"]

    def test_the_newest_ancestor_of_the_repository(self):
        from opp_repl.test.test_map.find import find_test_map
        self.assertEqual(self.header_commit(find_test_map(self.project, self.commits[3])), self.commits[2])
        self.assertEqual(self.header_commit(find_test_map(self.project, self.commits[1])), self.commits[0])

    def test_the_nearer_local_map_wins(self):
        from opp_repl.test.test_map.find import find_test_map
        write_files(self.root, {"coverage/test-map/map/header.json": json.dumps({"commit": self.commits[3]})})
        self.assertEqual(self.header_commit(find_test_map(self.project, self.commits[3])), self.commits[3])

class CheckTestSelectionTestCase(unittest.TestCase):
    def test_the_outcomes_of_a_result_file(self):
        from opp_repl.test.test_map.check import read_test_outcomes
        data = {"result": "FAIL", "results": [{"result": "PASS", "expected": True, "results": [
            {"result": "PASS", "expected": True, "test_map_key": "fingerprint:a.ini:A:#0:1s:tplx"},
            {"result": "FAIL", "expected": False, "test_map_key": "fingerprint:a.ini:A:#0:1s:~tNl"}]}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
        try:
            self.assertEqual(read_test_outcomes(f.name), {"fingerprint:a.ini:A:#0:1s:tplx": ("PASS", True), "fingerprint:a.ini:A:#0:1s:~tNl": ("FAIL", False)})
        finally:
            os.remove(f.name)

class TopLevelItemsTestCase(unittest.TestCase):
    def items(self, text):
        return [(kind, first, last) for kind, first, last, _ in get_top_level_items(tokenize_cpp_lines(text))]

    def test_functions_declarations_and_directives(self):
        text = ('#include "a.h"\nnamespace inet {\nRegister_Class(X)\nstatic int count = 0;\nX::X(int a) : b(a), c{a}\n{\n    f([] { return 1; });\n}\n'
                'X& X::operator=(const X& o) { return *this; }\nauto h() -> int { return 2; }\nauto l = [](int x) { return x; };\nclass L { int x; };\n} // namespace inet\n')
        self.assertEqual(self.items(text), [("directive", 1, 1), ("other", 3, 3), ("other", 4, 4), ("function", 5, 8), ("function", 9, 9),
                                            ("function", 10, 10), ("other", 11, 11), ("other", 12, 12)])

    def test_unbalanced_braces_give_no_structure(self):
        self.assertIsNone(get_top_level_items(tokenize_cpp_lines("namespace inet {\nvoid f() {\n")))

class ReleaseOnlyTestCase(unittest.TestCase):
    """The release-only blocks of rule R-NDEBUG."""
    def blocks(self, text, texts=None):
        macros = find_release_dependent_macros(texts or [text])
        return sorted(find_release_only_blocks(text, macros))

    def test_the_branches_that_only_a_release_build_compiles(self):
        text = "#ifdef NDEBUG\na();\n#else\nb();\n#endif\n#ifndef NDEBUG\nc();\n#else\nd();\n#endif\n#if !defined(NDEBUG)\ne();\n#endif\n"
        self.assertEqual(self.blocks(text), [(1, 3), (8, 10)])

    def test_a_macro_that_depends_on_NDEBUG(self):
        # a guard around the definition, and a conditional on the macro in another file
        header = "#ifndef CHECK\n#ifdef NDEBUG\n#define CHECK 0\n#else\n#define CHECK 1\n#endif\n#endif\n"
        user = "#if CHECK\nf();\n#else\ng();\n#endif\n"
        self.assertEqual(find_release_dependent_macros([header, user])["CHECK"], {"release": ("defined", "0"), "debug": ("defined", "1")})
        self.assertEqual(self.blocks(user, [header, user]), [(3, 5)])
        self.assertEqual(self.blocks(header, [header, user]), [(2, 4)])

    def test_conditions_without_NDEBUG_give_no_block(self):
        text = "#if defined(A)\na();\n#elif defined(B)\nb();\n#else\nc();\n#endif\n#ifdef NDEBUG\n#if defined(A)\nd();\n#endif\n#endif\n"
        self.assertEqual(self.blocks(text), [(8, 12), (9, 11)])

    def test_a_definition_that_a_release_build_makes_and_a_debug_build_tests(self):
        # not a guard: the #ifndef comes after the definition
        text = "#ifdef NDEBUG\n#define QUIET\n#endif\n#ifndef QUIET\nlog();\n#else\nskip();\n#endif\n"
        self.assertEqual(self.blocks(text), [(1, 3), (6, 8)])

    def test_the_names_and_includes_of_a_block(self):
        with tempfile.TemporaryDirectory() as folder:
            write_files(folder, {"src/a.h": "#ifdef NDEBUG\n#include \"b.h\"\nint x = compute(1); // check()\n#endif\n", "src/b.h": "#include \"c.h\"\n", "src/c.h": "\n"})
            self.assertEqual(scan_release_only_blocks(folder, ["src/a.h", "src/b.h", "src/c.h"], ["src"]),
                             [{"path": "src/a.h", "lines": [1, 4], "names": ["compute", "x"], "includes": ["src/b.h", "src/c.h"]}])

    def test_simple_function_names(self):
        for name, simple in [("inet::Foo<int>::bar(int) const", "bar"), ("inet::Ipv4::~Ipv4()", "Ipv4"), ("f()", "f"),
                             ("inet::X::get<inet::Y>(std::function<void (int)>) const", "get")]:
            self.assertEqual(get_simple_function_name(name), simple)

def make_simulation_test_task(config):
    simulation_config = types.SimpleNamespace(working_directory="examples", ini_file="omnetpp.ini", config=config)
    return types.SimpleNamespace(simulation_task=types.SimpleNamespace(simulation_config=simulation_config, run_number=0, get_sim_time_limit=lambda: "1s"))

class TestSelectionTestCase(unittest.TestCase):
    def test_the_tasks_of_a_simulation_test_kind(self):
        with tempfile.TemporaryDirectory() as folder:
            for path, content in MAP_FILES.items():
                full_path = os.path.join(folder, path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w") as f:
                    json.dump(content, f)
            test_map = TestMap(folder)
            kind = KindSelection("statistical", tests=None)
            kind.selected["statistical:examples/omnetpp.ini:Two:#0:1s"] = [Reason("R2", "src/b.cc", "", "A..C")]
            changes = types.SimpleNamespace(describe=lambda: "worktree")
            selection = TestSelection(test_map, changes, folder, [], [], {"statistical": kind})
            tasks = types.SimpleNamespace(name="statistical test", tasks=[make_simulation_test_task(config) for config in ["One", "Two", "New"]])
            self.assertEqual(get_test_kind(tasks), "statistical")
            self.assertEqual(get_test_key("statistical", tasks.tasks[0]), "statistical:examples/omnetpp.ini:One:#0:1s")
            select_test_tasks("statistical", tasks, selection)
            # Two is selected, New is not in the map, and One is not selected
            self.assertEqual([task.simulation_task.simulation_config.config for task in tasks.tasks], ["Two", "New"])

    def test_tests_outside_the_map_and_line_shifts(self):
        with tempfile.TemporaryDirectory() as folder:
            for path, content in MAP_FILES.items():
                full_path = os.path.join(folder, path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w") as f:
                    json.dump(content, f)
            test_map = TestMap(folder)
            kind = KindSelection("fingerprint", tests=None)
            selection = TestSelection(test_map, None, folder, [], [], {"fingerprint": kind})
            self.assertTrue(selection.is_selected("fingerprint", "fingerprint:examples/new.ini:General:#0:1s:tplx"))
            self.assertFalse(selection.is_selected("fingerprint", "fingerprint:examples/omnetpp.ini:One:#0:1s:tplx"))
            self.assertTrue(selection.is_selected("smoke", "smoke:x"))
            # a kind without records: selected only if a rule selects all of its tests
            selection = TestSelection(test_map, None, folder, [], [], {"feature": KindSelection("feature", tests=None)})
            self.assertFalse(selection.is_selected("feature", "feature:enable:X"))
            self.assertEqual(test_map.get_abnormal_runs(), 1 << 2)

if __name__ == "__main__":
    unittest.main()
