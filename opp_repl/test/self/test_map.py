#!/usr/bin/env python3
"""
Tests the record part and the build tables of the test map: the run key and id, the readers of the
profile list, the Cmdenv output and the section query, the reduction of a file trace, the readers
of the build tables, and the file trace library on a real process.
"""

import os
import subprocess
import tempfile
import types
import unittest

from opp_repl.test.test_map.build import *
from opp_repl.test.test_map.record import *

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
