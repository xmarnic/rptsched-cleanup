import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import report_orphans


class TestReportOrphansCli(unittest.TestCase):
    def test_reads_candidates_from_file(self):
        with TemporaryDirectory() as tmp:
            candidates_file = Path(tmp) / "candidates.jsonl"
            candidates_file.write_text(json.dumps({
                "schema_version": 1, "id": "wxyz", "filenames": ["wxyz.set", "wxyz.user"],
            }) + "\n")

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = report_orphans.main(["--candidates-file", str(candidates_file)])

            self.assertEqual(exit_code, 0)
            self.assertIn("1 orphan id(s), 2 file(s)", out.getvalue())
            self.assertIn("wxyz", out.getvalue())

    def test_reads_candidates_from_stdin_by_default(self):
        import sys
        record = json.dumps({"schema_version": 1, "id": "wxyz", "filenames": ["wxyz.set"]})
        real_stdin = sys.stdin
        sys.stdin = io.StringIO(record + "\n")
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = report_orphans.main([])
        finally:
            sys.stdin = real_stdin

        self.assertEqual(exit_code, 0)
        self.assertIn("1 orphan id(s), 1 file(s)", out.getvalue())

    def test_empty_stream_reports_zero(self):
        with TemporaryDirectory() as tmp:
            candidates_file = Path(tmp) / "candidates.jsonl"
            candidates_file.write_text("")

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = report_orphans.main(["--candidates-file", str(candidates_file)])

            self.assertEqual(exit_code, 0)
            self.assertIn("0 orphan id(s), 0 file(s)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
