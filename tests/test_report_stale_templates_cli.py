import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from composables import report_stale_templates
from tests.fixtures import make_rptsched_dir

STALE_LINE = "wxyz|noverdue|Stale Template|n|200207021051|202001010000|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"
ACTIVE_LINE = "abcd|noverdue|Active Template|n|200207021051|202001010000|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"


def _candidate_record(**overrides):
    record = {
        "schema_version": 1,
        "id": "wxyz",
        "report_source": "noverdue",
        "description": "Stale Template",
        "owner": "SOMEMGR",
        "frequency_flag": "n",
        "created": "200207021051",
        "raw_line": STALE_LINE,
        "filenames": ["wxyz.set", "wxyz.selans"],
    }
    record.update(overrides)
    return record


class TestReportStaleTemplatesCli(unittest.TestCase):
    def test_reads_candidates_from_stdin_by_default(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            stdin = io.StringIO(json.dumps(_candidate_record()) + "\n")

            out = io.StringIO()
            with redirect_stdout(out):
                import sys
                real_stdin = sys.stdin
                sys.stdin = stdin
                try:
                    exit_code = report_stale_templates.main(["--rptsched-dir", str(rptsched_dir)])
                finally:
                    sys.stdin = real_stdin

            self.assertEqual(exit_code, 0)
            self.assertIn("1 of 2 manual templates removed", out.getvalue())

    def test_reads_candidates_from_file(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            candidates_file = Path(tmp) / "candidates.jsonl"
            candidates_file.write_text(json.dumps(_candidate_record()) + "\n")

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = report_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--candidates-file", str(candidates_file),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("SUMMARY", out.getvalue())
            self.assertIn("BY OWNER", out.getvalue())
            self.assertIn("wxyz", out.getvalue())

    def test_empty_candidate_stream_reports_nothing_to_do(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [ACTIVE_LINE], ["abcd.set"])
            candidates_file = Path(tmp) / "candidates.jsonl"
            candidates_file.write_text("")

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = report_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--candidates-file", str(candidates_file),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("nothing to report", out.getvalue())

    def test_does_not_modify_rptsched_dir(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set", "wxyz.selans"])
            candidates_file = Path(tmp) / "candidates.jsonl"
            candidates_file.write_text(json.dumps(_candidate_record()) + "\n")
            schedlist_before = (rptsched_dir / "schedlist").read_text()

            with redirect_stdout(io.StringIO()):
                report_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--candidates-file", str(candidates_file),
                ])

            self.assertEqual((rptsched_dir / "schedlist").read_text(), schedlist_before)

    def test_active_duplicates_section_finds_byte_identical_set_files_regardless_of_description(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [
                STALE_LINE,
                "aaaa|list|Branch A List|n|200207021051|202001010000|SOMEMGR||||||0|3||0|||",
                "bbbb|list|Branch B List|n|200207021051|202001010000|SOMEMGR||||||0|3||0|||",
            ], ["wxyz.set", "wxyz.selans", "aaaa.set", "bbbb.set"])
            (rptsched_dir / "aaaa.set").write_text("identical content\n")
            (rptsched_dir / "bbbb.set").write_text("identical content\n")
            candidates_file = Path(tmp) / "candidates.jsonl"
            candidates_file.write_text(json.dumps(_candidate_record()) + "\n")

            out = io.StringIO()
            with redirect_stdout(out):
                report_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--candidates-file", str(candidates_file),
                ])

            self.assertIn("aaaa", out.getvalue())
            self.assertIn("bbbb", out.getvalue())
            self.assertIn("Branch A List", out.getvalue())

    def test_exclude_owner_matches_detect_side_and_excludes_from_active_population(self):
        with TemporaryDirectory() as tmp:
            excluded_line = "qzqz|list|Excluded Owner Template|n|200207021051|202001010000|ACQMGR||||||0|3||0|||"
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE, excluded_line], ["wxyz.set", "wxyz.selans", "qzqz.set"])
            candidates_file = Path(tmp) / "candidates.jsonl"
            candidates_file.write_text(json.dumps(_candidate_record()) + "\n")

            out = io.StringIO()
            with redirect_stdout(out):
                report_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--candidates-file", str(candidates_file),
                    "--exclude-owner", "ACQMGR",
                ])

            self.assertNotIn("ACQMGR", out.getvalue())

    def test_exclude_report_source_matches_detect_side_and_excludes_from_active_population(self):
        with TemporaryDirectory() as tmp:
            excluded_line = "qzqz|liststats|Excluded Source Template|n|200207021051|202001010000|SOMEMGR||||||0|3||0|||"
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE, excluded_line], ["wxyz.set", "wxyz.selans", "qzqz.set"])
            candidates_file = Path(tmp) / "candidates.jsonl"
            candidates_file.write_text(json.dumps(_candidate_record()) + "\n")

            out = io.StringIO()
            with redirect_stdout(out):
                report_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--candidates-file", str(candidates_file),
                    "--exclude-report-source", "liststats",
                ])

            self.assertNotIn("qzqz", out.getvalue())


if __name__ == "__main__":
    unittest.main()
