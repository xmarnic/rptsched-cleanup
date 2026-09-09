import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from composables import report_operators


class TestReportOperatorsCli(unittest.TestCase):
    def test_reads_candidates_from_file(self):
        with TemporaryDirectory() as tmp:
            candidates_file = Path(tmp) / "candidates.jsonl"
            candidates_file.write_text(json.dumps({
                "schema_version": 1, "id": "abcd", "old_operator": "OLDMGR", "new_operator": "NEWMGR",
            }) + "\n")

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = report_operators.main(["--candidates-file", str(candidates_file)])

            self.assertEqual(exit_code, 0)
            self.assertIn("1 operator mismatch(es) found", out.getvalue())
            self.assertIn("abcd: OLDMGR -> NEWMGR", out.getvalue())

    def test_empty_stream_reports_zero(self):
        with TemporaryDirectory() as tmp:
            candidates_file = Path(tmp) / "candidates.jsonl"
            candidates_file.write_text("")

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = report_operators.main(["--candidates-file", str(candidates_file)])

            self.assertEqual(exit_code, 0)
            self.assertIn("0 operator mismatch(es) found", out.getvalue())


if __name__ == "__main__":
    unittest.main()
