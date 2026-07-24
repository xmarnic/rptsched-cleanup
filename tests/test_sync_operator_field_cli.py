import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import sync_operator_field
from rptsched_cleanup.operators import read_operator_manifest
from tests.fixtures import make_data_dir

MATCHING_LINE = "aaaa|noverdue|Matching Template|n|200207021051|202001010000|SAMEOWNER||||||0|3||0|$<library_notice:c>|ENGLISH|"
MISMATCH_LINE = "bbbb|noverdue|Mismatch Template|n|200207021051|202001010000|REALOWNER||||||0|3||0|$<library_notice:c>|ENGLISH|"


def _write_set_file(data_dir, template_id, operator_value):
    (data_dir / "{}.set".format(template_id)).write_text(
        "desc|0||$(14837)|\noperator|0||{}|\ntitle|0||-t$(14836)|\n".format(operator_value)
    )


class TestDryRun(unittest.TestCase):
    def test_dry_run_reports_mismatches_and_changes_nothing(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [MATCHING_LINE, MISMATCH_LINE], [])
            _write_set_file(data_dir, "aaaa", "SAMEOWNER")
            _write_set_file(data_dir, "bbbb", "STALEOWNER")
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("bbbb", out.getvalue())
            self.assertIn("STALEOWNER", out.getvalue())
            self.assertIn("REALOWNER", out.getvalue())
            self.assertNotIn("aaaa", out.getvalue())
            self.assertFalse(quarantine_dir.exists())
            self.assertIn("STALEOWNER", (data_dir / "bbbb.set").read_text())

    def test_dry_run_prints_warning_for_missing_set_file(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [MISMATCH_LINE], [])
            # bbbb.set intentionally not written
            quarantine_dir = Path(tmp) / "quarantine"

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("bbbb", err.getvalue())
            self.assertIn("missing .set file", err.getvalue())

    def test_missing_required_args_errors(self):
        with self.assertRaises(SystemExit):
            sync_operator_field.main([])


class TestExecute(unittest.TestCase):
    def test_execute_rewrites_operator_and_writes_manifest(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [MATCHING_LINE, MISMATCH_LINE], [])
            _write_set_file(data_dir, "aaaa", "SAMEOWNER")
            _write_set_file(data_dir, "bbbb", "STALEOWNER")
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("REALOWNER", (data_dir / "bbbb.set").read_text())
            self.assertIn("SAMEOWNER", (data_dir / "aaaa.set").read_text())

            run_dirs = list(quarantine_dir.glob("operators_*"))
            self.assertEqual(len(run_dirs), 1)
            rows = read_operator_manifest(run_dirs[0])
            self.assertEqual(rows, [{"id": "bbbb", "old_operator": "STALEOWNER", "new_operator": "REALOWNER"}])

    def test_execute_with_no_mismatches_touches_nothing(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [MATCHING_LINE], [])
            _write_set_file(data_dir, "aaaa", "SAMEOWNER")
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertFalse(quarantine_dir.exists())
            self.assertIn("no operator mismatch", out.getvalue().lower())

    def test_execute_aborts_and_reports_error_on_rewrite_failure(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [MISMATCH_LINE], [])
            _write_set_file(data_dir, "bbbb", "STALEOWNER")
            quarantine_dir = Path(tmp) / "quarantine"

            with patch("rptsched_cleanup.operators.os.replace", side_effect=OSError("simulated failure")):
                err = io.StringIO()
                with redirect_stdout(io.StringIO()), redirect_stderr(err):
                    exit_code = sync_operator_field.main([
                        "--data-dir", str(data_dir),
                        "--quarantine-dir", str(quarantine_dir),
                        "--execute",
                    ])

            self.assertEqual(exit_code, 1)
            self.assertIn("simulated failure", err.getvalue())
            self.assertIn("STALEOWNER", (data_dir / "bbbb.set").read_text())


if __name__ == "__main__":
    unittest.main()
