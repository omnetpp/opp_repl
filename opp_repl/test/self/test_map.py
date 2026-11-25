#!/usr/bin/env python3
"""
Tests the record part of the test map: the run key and id, the readers of the profile list, the
Cmdenv output and the section query, the reduction of a file trace, and the file trace library on a
real process.
"""

import os
import subprocess
import tempfile
import types
import unittest

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
