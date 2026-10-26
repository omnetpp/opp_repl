#!/usr/bin/env python3
"""
Tests the lcov part of the coverage report: the merge of several lcov files, the counts of the
summary, the areas, the change against an earlier summary and the rewrite of an export.
"""

import json
import os
import tempfile
import unittest

from opp_repl.test.coverage import *

# One suite reaches f() and one branch of line 11; the other suite reaches g() and both suites
# leave h() and B.cc unexecuted. The "-" branches of line 21 belong to a block that the first
# suite never ran.
FINGERPRINT_LCOV = """TN:fingerprint
SF:src/inet/a/A.cc
FN:10,_Z1fv
FN:20,_Z1gv
FNDA:3,_Z1fv
FNDA:0,_Z1gv
FNF:2
FNH:1
BRDA:11,0,0,2
BRDA:11,0,1,0
BRDA:21,0,0,-
BRDA:21,0,1,-
BRF:4
BRH:1
DA:10,3
DA:11,3
DA:20,0
DA:21,0
LF:4
LH:2
end_of_record
"""

MODULE_LCOV = """TN:module
SF:src/inet/a/A.cc
FN:20,_Z1gv
FNDA:1,_Z1gv
BRDA:21,0,0,1
BRDA:21,0,1,0
DA:20,1
DA:21,1
end_of_record
TN:module
SF:src/inet/b/B.cc
FN:5,_Z1hv
FNDA:0,_Z1hv
DA:5,0
DA:6,0
end_of_record
"""

class CoverageReportTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.fingerprint_file = self.write("fingerprint.lcov", FINGERPRINT_LCOV)
        self.module_file = self.write("module.lcov", MODULE_LCOV)

    def tearDown(self):
        self.folder.cleanup()

    def write(self, name, text):
        file_name = os.path.join(self.folder.name, name)
        with open(file_name, "w") as f:
            f.write(text)
        return file_name

    def counts(self, summary_part):
        return {metric: (summary_part[metric]["hit"], summary_part[metric]["found"]) for metric in ["lines", "functions", "branches"]}

    def test_totals_add_up_the_suites(self):
        summary = summarize_coverage(read_lcov_files([self.fingerprint_file, self.module_file]))
        self.assertEqual(self.counts(summary["totals"]), {"lines": (4, 6), "functions": (2, 3), "branches": (2, 4)})

    def test_each_suite_has_its_own_totals(self):
        summary = summarize_coverage(read_lcov_files([self.fingerprint_file, self.module_file]))
        self.assertEqual(self.counts(summary["suites"]["fingerprint"]), {"lines": (2, 4), "functions": (1, 2), "branches": (1, 4)})
        self.assertEqual(self.counts(summary["suites"]["module"]), {"lines": (2, 4), "functions": (1, 2), "branches": (1, 2)})

    def test_areas_follow_the_pattern(self):
        summary = summarize_coverage(read_lcov_files([self.fingerprint_file, self.module_file]), "src/inet/*")
        self.assertEqual(list(summary["areas"]), ["src/inet/a", "src/inet/b"])
        self.assertEqual(self.counts(summary["areas"]["src/inet/b"])["lines"], (0, 2))
        self.assertEqual(get_coverage_area("src/inet/features.h", "src/inet/*"), "other")
        self.assertEqual(get_coverage_area("src/inet/a/A.cc", None), "other")

    def test_a_file_merged_with_itself_keeps_the_covered_set(self):
        once = summarize_coverage(read_lcov_files([self.fingerprint_file]))
        twice = summarize_coverage(read_lcov_files([self.fingerprint_file, self.fingerprint_file]))
        self.assertEqual(once["totals"], twice["totals"])
        merged = merge_lcov_tests(read_lcov_files([self.fingerprint_file, self.fingerprint_file]))
        self.assertEqual(merged["src/inet/a/A.cc"]["lines"][10], 6)

    def test_written_lcov_reads_back_the_same(self):
        tests = read_lcov_files([self.fingerprint_file, self.module_file])
        merged_file = os.path.join(self.folder.name, "merged.lcov")
        write_lcov_file(merge_lcov_tests(tests), merged_file)
        self.assertEqual(summarize_coverage(read_lcov_files([merged_file]))["totals"], summarize_coverage(tests)["totals"])
        with open(merged_file) as f:
            text = f.read()
        self.assertIn("BRDA:21,0,0,1\n", text)
        self.assertIn("BRDA:11,0,1,0\n", text)

    def test_a_block_that_never_ran_keeps_its_dash(self):
        merged_file = os.path.join(self.folder.name, "merged.lcov")
        write_lcov_file(merge_lcov_tests(read_lcov_files([self.fingerprint_file])), merged_file)
        with open(merged_file) as f:
            self.assertIn("BRDA:21,0,0,-\n", f.read())

    def test_change_against_a_previous_history_line(self):
        history_file = self.write("history.jsonl", json.dumps({"commit": "old", "totals": {"lines": {"hit": 1, "found": 2}}}) + "\n")
        summary = coverage_report([self.fingerprint_file, self.module_file], output_folder=os.path.join(self.folder.name, "report"), previous_file=history_file, commit="new")
        self.assertAlmostEqual(summary["change"]["lines"], 100 * 4 / 6 - 50, places=3)
        self.assertIsNone(summary["change"]["functions"])
        with open(os.path.join(self.folder.name, "report", "summary.md")) as f:
            markdown = f.read()
        self.assertIn("| lines | 4 | 6 | 66.67% | +16.67 |", markdown)
        self.assertIn("| fingerprint |", markdown)

    def test_report_writes_its_files(self):
        output_folder = os.path.join(self.folder.name, "report")
        coverage_report([self.fingerprint_file, self.module_file], output_folder=output_folder, commit="abc", date="2026-10-26")
        self.assertEqual(sorted(os.listdir(output_folder)), ["coverage.lcov", "history.json", "summary.json", "summary.md"])
        history = read_coverage_summary(os.path.join(output_folder, "history.json"))
        self.assertEqual(history["commit"], "abc")
        self.assertNotIn("files", history)
        self.assertIn("src/inet/b/B.cc", read_coverage_summary(os.path.join(output_folder, "summary.json"))["files"])

    def test_rewrite_makes_paths_relative_and_names_the_test(self):
        text = "SF:/root/src/a/A.cc\nDA:1,1\nend_of_record\nTN:old\nSF:/root/src/b/B.cc\nend_of_record\n"
        self.assertEqual(rewrite_lcov_text(text, "/root", "unit"),
                         "TN:unit\nSF:src/a/A.cc\nDA:1,1\nend_of_record\nTN:unit\nSF:src/b/B.cc\nend_of_record\n")
        self.assertEqual(rewrite_lcov_text(text, "/root"), "SF:src/a/A.cc\nDA:1,1\nend_of_record\nSF:src/b/B.cc\nend_of_record\n")

if __name__ == "__main__":
    unittest.main()
