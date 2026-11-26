#!/usr/bin/env python3
"""
Tests the test map: the run key and id, the readers of the profile list, the Cmdenv output and the
section query, the reduction of a file trace, the readers of the build tables, the NED type table and
closure, the map writer, the queries, and the file trace library on a real process.
"""

import os
import subprocess
import tempfile
import types
import unittest

from opp_repl.test.test_map.build import *
from opp_repl.test.test_map.record import *
from opp_repl.test.test_map.show import *
from opp_repl.test.test_map.writer import *

SHOW_OUTPUT = """Counters:
  _ZN4inet4Ipv48initiateEv:
    Hash: 0x0000000000000001
    Counters: 3
    Function count: 2
  _ZN4inet4Ipv46unusedEv:
    Hash: 0x0000000000000002
    Counters: 1
    Function count: 0
  Ipv4.cc:_ZL6helperv:
    Hash: 0x0000000000000003
    Counters: 1
    Function count: 7
Instrumentation level: Front-end
Functions shown: 3
"""

STDOUT = """Running simulation...
** Event #0   t=0   Elapsed: 0s
<!> Simulation time limit reached -- at t=10s, event #35168
instantiated NED type: inet.node.inet.StandardHost
instantiated NED type: inet.networklayer.ipv4.Ipv4
instantiated NED type: inet.node.inet.StandardHost

<!> Fingerprint successfully verified: 5144-4308/tplx
"""

def make_simulation_task(working_directory=".", ini_file="omnetpp.ini", config="General", run_number=0, sim_time_limit=None):
    simulation_config = types.SimpleNamespace(working_directory=working_directory, ini_file=ini_file, config=config)
    return types.SimpleNamespace(simulation_config=simulation_config, run_number=run_number, get_sim_time_limit=lambda: sim_time_limit)

class RunKeyTestCase(unittest.TestCase):
    def test_key_has_the_ini_path_config_run_and_limit(self):
        task = make_simulation_task("examples/adhoc/hostautoconf", "omnetpp.ini", "General", 0, "100s")
        self.assertEqual(get_test_map_run_key("fingerprint", task), "fingerprint:examples/adhoc/hostautoconf/omnetpp.ini:General:#0:100s")

    def test_key_of_an_ini_file_in_the_root_and_no_limit(self):
        self.assertEqual(get_test_map_run_key("smoke", make_simulation_task(".", "a.ini", "X", 3)), "smoke:a.ini:X:#3:")

    def test_id_is_stable_and_short(self):
        run_id = get_test_map_run_id("fingerprint:a.ini:General:#0:1s")
        self.assertEqual(run_id, get_test_map_run_id("fingerprint:a.ini:General:#0:1s"))
        self.assertEqual(len(run_id), 10)
        self.assertNotEqual(run_id, get_test_map_run_id("fingerprint:a.ini:General:#1:1s"))

class ReaderTestCase(unittest.TestCase):
    def test_functions_that_ran_have_a_count(self):
        self.assertEqual(read_functions_that_ran(SHOW_OUTPUT), ["_ZN4inet4Ipv48initiateEv", "Ipv4.cc:_ZL6helperv"])

    def test_ned_types_are_sorted_and_unique(self):
        self.assertEqual(read_instantiated_ned_types(STDOUT), ["inet.networklayer.ipv4.Ipv4", "inet.node.inet.StandardHost"])

    def test_end_is_the_stop_line_and_not_the_fingerprint_line(self):
        self.assertEqual(read_end_of_run(STDOUT), {"text": "Simulation time limit reached -- at t=10s, event #35168", "event": 35168, "sim_time": "10s"})

    def test_end_of_an_error(self):
        end = read_end_of_run("<!> Error: Cannot open file -- in module (inet::Foo) Net.foo (id=5), at t=1.5s, event #12\n")
        self.assertEqual((end["event"], end["sim_time"]), (12, "1.5s"))

    def test_end_without_a_stop_line(self):
        self.assertEqual(read_end_of_run("no output\n"), {"text": None, "event": None, "sim_time": None})

    def test_section_chain(self):
        self.assertEqual(read_section_chain("Config DynamicIPv4\nConfig _Dynamic\nGeneral\n"), ["Config DynamicIPv4", "Config _Dynamic", "General"])

class ReduceFileTraceTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.folder.name)
        for path in ["src/a/A.ned", "src/a/data.xml", "examples/x/omnetpp.ini", "examples/x/results/General-#0.sca", "out/clang-coverage/a.o"]:
            os.makedirs(os.path.dirname(os.path.join(self.root, path)), exist_ok=True)
            open(os.path.join(self.root, path), "w").close()
        os.symlink(os.path.join(self.root, "missing"), os.path.join(self.root, "examples/x/media"))

    def tearDown(self):
        self.folder.cleanup()

    def reduce(self, lines):
        return reduce_file_trace([line.replace("$R", self.root) + "\n" for line in lines], self.root, output_folders=["examples/x/results"])

    def test_kinds(self):
        self.assertEqual(self.reduce(["open ok $R/examples/x/omnetpp.ini", "stat ok $R/src/a/data.xml", "list ok $R/src", "open fail $R/examples/x/missing.xml"]),
                         [("examined", "src/a/data.xml"), ("listed", "src"), ("lookup", "examples/x/missing.xml"), ("read", "examples/x/omnetpp.ini")])

    def test_ned_walk_and_ned_reads_are_left_out(self):
        self.assertEqual(self.reduce(["glob ok $R/src/a/*", "stat ok $R/src/a/data.xml", "open ok $R/src/a/A.ned", "stat fail $R/src/a/package.ned"]),
                         [("lookup", "src/a/package.ned")])

    def test_outputs_build_files_and_outside_paths_are_left_out(self):
        self.assertEqual(self.reduce(["write ok $R/examples/x/out.txt", "stat fail $R/examples/x/results/General-#0.elog", "stat ok $R/examples/x/results",
                                      "open ok $R/out/clang-coverage/a.o", "open ok /etc/passwd", "openat ok relative/to/a/descriptor"]), [])

    def test_a_broken_link_is_not_a_lookup(self):
        self.assertEqual(self.reduce(["stat fail $R/examples/x/media"]), [])

    def test_the_path_is_normalized(self):
        self.assertEqual(self.reduce(["open ok $R/examples/x/../x/omnetpp.ini"]), [("read", "examples/x/omnetpp.ini")])

class BuildTablesTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.folder.name)
        for path in ["src/inet/a/A.cc", "src/inet/a/A.h", "src/inet/b/B.c", "out/clang-coverage/src/inet/a/A.o", "out/clang-coverage/src/inet/b/B.o"]:
            os.makedirs(os.path.dirname(os.path.join(self.root, path)), exist_ok=True)
            open(os.path.join(self.root, path), "w").close()

    def tearDown(self):
        self.folder.cleanup()

    def test_counter_symbol_of_an_external_and_a_local_function(self):
        self.assertEqual(get_counter_symbol("_ZN4inet4Ipv48initiateEv"), "__profc__ZN4inet4Ipv48initiateEv")
        self.assertEqual(get_counter_symbol("SGP4.cc:_ZN9SGP4FuncsL5initlEv"), "__profc_SGP4.cc__ZN9SGP4FuncsL5initlEv")
        self.assertEqual(get_counter_symbol("inet/a/A.cc;_ZL1fv"), "__profc_inet_a_A.cc__ZL1fv")

    def test_function_table_uses_the_regions_of_file_0(self):
        export = {"data": [{"functions": [
            {"name": "_Z1fv", "filenames": [self.root + "/src/inet/a/A.cc", self.root + "/src/inet/a/A.h"],
             "regions": [[10, 1, 20, 2, 5, 0, 0, 0], [12, 1, 13, 2, 0, 0, 0, 2], [3, 1, 4, 2, 5, 1, 0, 0]]},
            {"name": "_Z1gv", "filenames": ["/usr/include/omnetpp/cobject.h"], "regions": [[1, 1, 2, 2, 0, 0, 0, 0]]}]}]}
        self.assertEqual(read_function_table(export, self.root), [["_Z1fv", "src/inet/a/A.cc", 10, 20]])

    def test_nm_counters_of_each_object(self):
        output = ("/o/A.o:0000000000000000 V __profc__Z1fv\n/o/A.o:0000000000000010 T _Z1fv\n"
                  "/o/A.o:0000000000000000 n __profc_A.cc__ZL1gv\n/o/B.o:0000000000000000 V __profc__Z1fv\n/o/B.o:0000000000000000 d __profd__Z1fv\n")
        self.assertEqual(dict(read_nm_counters(output)), {"/o/A.o": {"__profc__Z1fv", "__profc_A.cc__ZL1gv"}, "/o/B.o": {"__profc__Z1fv"}})

    def test_translation_unit_of_an_object(self):
        self.assertEqual(get_translation_unit(self.root, "src", "out/clang-coverage/src", self.root + "/out/clang-coverage/src/inet/a/A.o"), "src/inet/a/A.cc")
        self.assertEqual(get_translation_unit(self.root, "src", "out/clang-coverage/src", self.root + "/out/clang-coverage/src/inet/b/B.o"), "src/inet/b/B.c")

    def test_dependency_file_paths_are_relative_to_the_cpp_folder(self):
        text = "../out/clang-coverage/src/inet/a/A.o: \\\n  inet/a/A.cc inet/a/A.h \\\n  /usr/include/stdio.h\ninet/a/A.h:\n"
        self.assertEqual(read_dependency_file(text, self.root, "src"), ("src/inet/a/A.cc", ["src/inet/a/A.h"]))

NED_XML = """<files>
<ned-file filename="src/a/Host.ned">
  <package name="a"/>
  <import import-spec="b.Base"/>
  <import import-spec="c.**"/>
  <compound-module name="Host">
    <extends name="Base"/>
    <interface-name name="INode"/>
    <types>
      <channel name="Link"><extends name="Cable"/></channel>
      <channel name="Cable"/>
    </types>
    <submodules>
      <submodule name="app" like-type="IApp"/>
      <submodule name="eth" type="Eth"/>
    </submodules>
    <connections>
      <connection src-module="app" dest-module="eth" type="Link"/>
      <connection src-module="app" dest-module="eth" like-type="Link"/>
    </connections>
  </compound-module>
  <module-interface name="INode"/>
</ned-file>
<ned-file filename="src/b/Base.ned">
  <package name="b"/>
  <compound-module name="Base"><extends name="ned.Unknown"/></compound-module>
</ned-file>
<ned-file filename="src/c/d/IApp.ned">
  <package name="c.d"/>
  <module-interface name="IApp"/>
</ned-file>
</files>"""

class NedTypeTableTestCase(unittest.TestCase):
    def setUp(self):
        import xml.etree.ElementTree
        self.table, self.unresolved = read_ned_type_table(xml.etree.ElementTree.fromstring(NED_XML))

    def test_types_and_files(self):
        self.assertEqual(sorted(self.table), ["a.Host", "a.Host.Cable", "a.Host.Link", "a.INode", "b.Base", "c.d.IApp"])
        self.assertEqual(self.table["a.Host.Link"][0], "src/a/Host.ned")

    def test_references_resolve_by_import_package_wildcard_and_inner_type(self):
        # Base: exact import; INode: same package; IApp: wildcard import c.**; Link: inner type
        self.assertEqual(self.table["a.Host"][1], ["a.Host.Link", "a.INode", "b.Base", "c.d.IApp"])
        # an inner type extends another inner type of its compound module
        self.assertEqual(self.table["a.Host.Link"][1], ["a.Host.Cable"])

    def test_a_type_outside_the_table_is_unresolved(self):
        self.assertEqual(self.unresolved, ["ned.Unknown"])

    def test_closure_follows_the_references(self):
        self.assertEqual(get_ned_type_closure(["a.Host.Link", "ned.IdealChannel"], self.table), {"a.Host.Link", "a.Host.Cable", "ned.IdealChannel"})
        self.assertEqual(get_ned_type_closure(["a.Host"], self.table), {"a.Host", "a.Host.Link", "a.Host.Cable", "a.INode", "b.Base", "c.d.IApp"})

class WriterTestCase(unittest.TestCase):
    """Three runs: r0 and r1 ran f, only r2 ran g; all runs used the network type, only r1 read a data file."""

    def setUp(self):
        import gzip
        import json
        self.folder = tempfile.TemporaryDirectory()
        self.records_folder = os.path.join(self.folder.name, "records")
        self.map_folder = os.path.join(self.folder.name, "map")
        functions = {"r000000000": ["_Z1fv"], "r000000001": ["_Z1fv", "_Z1hv"], "r000000002": ["_Z1gv"]}
        files = {"r000000000": [], "r000000001": ["read examples/x/data.xml", "read examples/x/untracked.txt", "lookup examples/x/missing.xml"], "r000000002": ["listed examples/x"]}
        for index, run_id in enumerate(sorted(functions)):
            folder = os.path.join(self.records_folder, run_id)
            os.makedirs(folder)
            with gzip.open(os.path.join(folder, "functions.txt.gz"), "wt") as f:
                f.write("".join(name + "\n" for name in functions[run_id]))
            with open(os.path.join(folder, "files.txt"), "w") as f:
                f.write("".join(line + "\n" for line in files[run_id]))
            record = {"id": run_id, "key": f"fingerprint:examples/x/omnetpp.ini:C{index}:#0:1s", "kind": "fingerprint", "working_directory": "examples/x",
                      "ini_file": "omnetpp.ini", "config": f"C{index}", "run_number": 0, "sim_time_limit": "1s",
                      "args": ["opp_run", "--fingerprint", "1234-5678/tplx,0000-0000/~tNl"], "exit_code": 1 if index == 2 else 0,
                      "end": {"text": None, "event": None, "sim_time": None}, "profile": True, "ned_types": ["x.Net"], "sections": [f"Config C{index}", "General"]}
            with open(os.path.join(folder, "run.json"), "w") as f:
                json.dump(record, f)
        self.build_tables = {"functions": [["_Z1fv", "src/a/A.cc", 10, 20], ["_Z1gv", "src/a/A.cc", 30, 40], ["_Z1hv", "src/a/A.h", 5, 6], ["_Z1kv", "src/a/A.cc", 50, 60]],
                             "emitters": {"2": ["src/a/A.cc", "src/b/B.cc"]}, "includes": {"src/a/A.cc": ["src/a/A.h"], "src/b/B.cc": ["src/a/A.h"]},
                             "ned_types": {"x.Net": ["examples/x/Net.ned", ["x.INet"]], "x.INet": ["examples/x/INet.ned", []]}, "ned_errors": []}
        self.numbers = write_test_map(read_test_map_records([self.records_folder]), self.build_tables, self.folder.name, self.map_folder,
                                      header={"project": "x"}, tracked_files={"examples/x/data.xml"})

    def tearDown(self):
        self.folder.cleanup()

    def read(self, path):
        import json
        with open(os.path.join(self.map_folder, path)) as f:
            return json.load(f)

    def test_functions_and_their_runs(self):
        functions = self.read("src/a/A.cc.json")["functions"]
        self.assertEqual([item["lines"] for item in functions], [[10, 20], [30, 40], [50, 60]])
        self.assertEqual(functions[0]["runs"], {"except": ["r000000002"]})
        self.assertEqual(functions[1]["runs"], ["r000000002"])
        self.assertNotIn("runs", functions[2])

    def test_translation_units_and_includes(self):
        self.assertEqual(self.read("src/a/A.cc.json")["tu_runs"], "all")
        self.assertEqual(self.read("src/b/B.cc.json")["tu_runs"], ["r000000001"])
        header = self.read("src/a/A.h.json")
        self.assertEqual(header["functions"][0]["tus"], ["src/a/A.cc", "src/b/B.cc"])
        self.assertEqual(header["included_by"], ["src/a/A.cc", "src/b/B.cc"])

    def test_more_than_20_emitters_are_a_set(self):
        import json
        units = [f"src/t/T{index:02}.cc" for index in range(21)]
        build_tables = dict(self.build_tables, functions=self.build_tables["functions"] + [["_Z1mv", "src/a/A.h", 8, 9]],
                            emitters=dict(self.build_tables["emitters"], **{"4": units}))
        map_folder = os.path.join(self.folder.name, "map2")
        write_test_map(read_test_map_records([self.records_folder]), build_tables, self.folder.name, map_folder, header={"project": "x"}, tracked_files=set())
        with open(os.path.join(map_folder, "src/a/A.h.json")) as f:
            item = json.load(f)["functions"][1]
        self.assertEqual(item["tus"]["count"], 21)
        with open(os.path.join(map_folder, "emitter-sets.json")) as f:
            self.assertEqual(json.load(f)["sets"][item["tus"]["set"]], units)

    def test_ned_types_include_the_closure(self):
        self.assertEqual(self.read("examples/x/Net.ned.json")["types"], {"x.Net": "all"})
        self.assertEqual(self.read("examples/x/INet.ned.json")["types"], {"x.INet": "all"})

    def test_sections(self):
        self.assertEqual(self.read("examples/x/omnetpp.ini.json")["sections"], {"Config C0": ["r000000000"], "Config C1": ["r000000001"], "Config C2": ["r000000002"], "General": "all"})

    def test_data_keeps_tracked_files_and_all_lookups(self):
        self.assertEqual(self.read("examples/x/data.xml.json")["data"], {"read": ["r000000001"]})
        self.assertEqual(self.read("examples/x/missing.xml.json")["data"], {"lookup": ["r000000001"]})
        self.assertFalse(os.path.exists(os.path.join(self.map_folder, "examples/x/untracked.txt.json")))

    def test_folder_index(self):
        self.assertEqual(self.read("examples/x/index.json"), {"data": 1, "ini": 3, "listed": ["r000000002"], "ned": 3})
        self.assertEqual(self.read("src/index.json"), {"functions": 3})

    def test_runs_and_tests(self):
        runs = self.read("runs.json")
        self.assertEqual([runs[run_id]["normal_end"] for run_id in sorted(runs)], [True, True, False])
        tests = self.read("tests.json")["fingerprint"]
        self.assertEqual(tests["fingerprint:examples/x/omnetpp.ini:C0:#0:1s:~tNl"], ["r000000000"])
        self.assertEqual(len(tests), 6)

    def test_a_folder_that_is_no_map_is_not_removed(self):
        other = os.path.join(self.folder.name, "other")
        os.makedirs(other)
        open(os.path.join(other, "keep.txt"), "w").close()
        with self.assertRaises(Exception):
            write_test_map(read_test_map_records([self.records_folder]), self.build_tables, self.folder.name, other, tracked_files=set())
        self.assertTrue(os.path.exists(os.path.join(other, "keep.txt")))

    def test_records_folder_with_other_files_is_not_cleared(self):
        open(os.path.join(self.records_folder, "notes.txt"), "w").close()
        with self.assertRaises(Exception):
            clear_test_map_records(self.records_folder)
        self.assertTrue(os.path.exists(os.path.join(self.records_folder, "r000000000", "run.json")))

    def test_show_the_tests_of_a_line(self):
        import io
        output = io.StringIO()
        show_test_map(self.map_folder, path="src/a/A.cc", line=35, output_stream=output)
        self.assertIn("src/a/A.cc:30-40", output.getvalue())
        self.assertIn("fingerprint:examples/x/omnetpp.ini:C2:#0:1s:tplx", output.getvalue())
        self.assertNotIn("C0", output.getvalue())

    def test_a_run_that_a_cpu_time_limit_stopped_did_not_end_normally(self):
        record = {"exit_code": 0, "profile": True, "sections": ["General"], "ned_types": [], "end": {"text": "CPU time limit reached -- at t=0.5s, event #10"}}
        self.assertFalse(is_normal_end(record))
        record["end"]["text"] = "Simulation time limit reached -- at t=0.5s, event #10"
        self.assertTrue(is_normal_end(record))
        # a run whose NED types are not known, for example of a %testprog program
        self.assertFalse(is_normal_end(dict(record, ned_types=None)))

    def test_a_smoke_record_is_also_the_run_of_the_sanitizer_test(self):
        import json
        records = read_test_map_records([self.records_folder])
        records[0] = dict(records[0], kind="smoke", key="smoke:examples/x/omnetpp.ini:C0:#0:1s")
        map_folder = os.path.join(self.folder.name, "map3")
        write_test_map(records, self.build_tables, self.folder.name, map_folder, header={"project": "x"}, tracked_files=set())
        with open(os.path.join(map_folder, "tests.json")) as f:
            tests = json.load(f)
        self.assertEqual(tests["smoke"], {"smoke:examples/x/omnetpp.ini:C0:#0:1s": ["r000000000"]})
        self.assertEqual(tests["sanitizer"], {"sanitizer:examples/x/omnetpp.ini:C0:#0:1s": ["r000000000"]})

    def test_the_headers_that_the_own_code_of_a_test_includes(self):
        import json
        records = read_test_map_records([self.records_folder])
        records[1] = dict(records[1], kind="unit", key="unit:tests/unit/A.test", ini_file=None, includes=["src/a/A.h", "tests/unit/Support.h"])
        map_folder = os.path.join(self.folder.name, "map4")
        write_test_map(records, self.build_tables, self.folder.name, map_folder, header={"project": "x"}, tracked_files=set())
        with open(os.path.join(map_folder, "tests/unit/Support.h.json")) as f:
            self.assertEqual(json.load(f)["test_runs"], ["r000000001"])
        with open(os.path.join(map_folder, "tests.json")) as f:
            self.assertEqual(json.load(f)["unit"], {"unit:tests/unit/A.test": ["r000000001"]})

    def test_the_includes_of_a_build(self):
        from opp_repl.test.opp import get_build_includes
        folder = os.path.join(self.folder.name, "tests", "x", "work", "T")
        os.makedirs(os.path.join(folder, "out"))
        os.makedirs(os.path.join(self.folder.name, "src", "a"), exist_ok=True)
        for name in ("src/a/A.h", "src/a/B.h"):
            open(os.path.join(self.folder.name, name), "w").close()
        with open(os.path.join(folder, "out", "test.d"), "w") as f:
            f.write("out/test.o: test.cc \\\n ../../../../src/a/A.h /usr/include/stdio.h \\\n ../../../../src/a/B.h test.h\n")
        open(os.path.join(folder, "test.h"), "w").close()
        self.assertEqual(get_build_includes(folder, self.folder.name), ["src/a/A.h", "src/a/B.h"])

    def test_fingerprint_ingredients(self):
        self.assertEqual(get_fingerprint_ingredients(["--fingerprint", "1234-5678/tplx,0000-0000/~tND"]), ["tplx", "~tND"])
        self.assertEqual(get_fingerprint_ingredients(["--fingerprint=1234-5678/tplx"]), ["tplx"])

class FileTraceLibraryTestCase(unittest.TestCase):
    def test_library_traces_a_process(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = os.path.realpath(folder)
            library = build_file_trace_library(folder)
            data_file = os.path.join(folder, "data.txt")
            open(data_file, "w").close()
            env = {**os.environ, "LD_PRELOAD": library, "OPP_REPL_FILE_TRACE": os.path.join(folder, "trace")}
            script = f"open({data_file!r}).read(); open({os.path.join(folder, 'out.txt')!r}, 'w').write('x'); import os; os.path.exists({os.path.join(folder, 'none')!r})"
            subprocess.run(["python3", "-c", script], env=env, check=True, cwd=folder)
            lines = []
            for name in os.listdir(folder):
                if name.startswith("trace."):
                    with open(os.path.join(folder, name)) as f:
                        lines += f.read().splitlines()
            self.assertIn(f"open ok {data_file}", lines)
            self.assertIn(f"write ok {os.path.join(folder, 'out.txt')}", lines)
            self.assertIn(f"stat fail {os.path.join(folder, 'none')}", lines)

if __name__ == "__main__":
    unittest.main()
