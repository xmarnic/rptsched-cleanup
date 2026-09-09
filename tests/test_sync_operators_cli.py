import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import sync_operators
from rptsched_lib.operators import read_operator
from tests.fixtures import make_data_dir


def _schedlist_line(template_id, owner):
    return "{}|noverdue|Some Template|n|200207021051|202001010000|{}||||||0|3||0|$<library_notice:c>|ENGLISH|".format(
        template_id, owner
    )


def _write_set_file(data_dir, template_id, operator_value):
    (data_dir / "{}.set".format(template_id)).write_text(
        "# Copyright (c) 1992 - 2000, Sirsi Corporation.\n"
        "desc|0||$(14837)|\n"
        "operator|0||{}|\n"
        "title|0||-t$(14836)|\n".format(operator_value)
    )


class TestBareDetect(unittest.TestCase):
    def test_saves_candidates_and_prints_count(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "NEWMGR")], [])
            _write_set_file(data_dir, "abcd", "OLDMGR")
            work_dir = Path(tmp) / "work"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = sync_operators.main(["--data-dir", str(data_dir), "--work-dir", str(work_dir)])

            self.assertEqual(exit_code, 0)
            self.assertIn("1 candidate(s) detected", out.getvalue())
            self.assertIn("abcd", (work_dir / "candidates.jsonl").read_text())
            self.assertEqual(read_operator(data_dir, "abcd"), "OLDMGR")


class TestReportFlag(unittest.TestCase):
    def test_prints_full_report(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "NEWMGR")], [])
            _write_set_file(data_dir, "abcd", "OLDMGR")
            work_dir = Path(tmp) / "work"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = sync_operators.main([
                    "--data-dir", str(data_dir), "--work-dir", str(work_dir), "--report",
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("1 operator mismatch(es) found", out.getvalue())
            self.assertIn("abcd: OLDMGR -> NEWMGR", out.getvalue())


class TestExecuteFlag(unittest.TestCase):
    def test_requires_prior_detect(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "NEWMGR")], [])
            _write_set_file(data_dir, "abcd", "OLDMGR")
            quarantine_dir = Path(tmp) / "quarantine"
            work_dir = Path(tmp) / "work"

            err = io.StringIO()
            with self.assertRaises(SystemExit), redirect_stderr(err):
                sync_operators.main([
                    "--data-dir", str(data_dir), "--quarantine-dir", str(quarantine_dir),
                    "--work-dir", str(work_dir), "--execute",
                ])

            self.assertIn("No candidates file found", err.getvalue())
            self.assertEqual(read_operator(data_dir, "abcd"), "OLDMGR")

    def test_applies_using_saved_candidates(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "NEWMGR")], [])
            _write_set_file(data_dir, "abcd", "OLDMGR")
            quarantine_dir = Path(tmp) / "quarantine"
            work_dir = Path(tmp) / "work"

            with redirect_stdout(io.StringIO()):
                sync_operators.main(["--data-dir", str(data_dir), "--work-dir", str(work_dir)])

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = sync_operators.main([
                    "--data-dir", str(data_dir), "--quarantine-dir", str(quarantine_dir),
                    "--work-dir", str(work_dir), "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Corrected 1 operator value(s)", out.getvalue())
            self.assertEqual(read_operator(data_dir, "abcd"), "NEWMGR")


class TestRestoreFlag(unittest.TestCase):
    def test_full_cycle_round_trips_cleanly(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "NEWMGR")], [])
            _write_set_file(data_dir, "abcd", "OLDMGR")
            quarantine_dir = Path(tmp) / "quarantine"
            work_dir = Path(tmp) / "work"

            with redirect_stdout(io.StringIO()):
                sync_operators.main(["--data-dir", str(data_dir), "--work-dir", str(work_dir)])
                sync_operators.main([
                    "--data-dir", str(data_dir), "--quarantine-dir", str(quarantine_dir),
                    "--work-dir", str(work_dir), "--execute",
                ])

            run_dir = list(quarantine_dir.glob("operators_*"))[0]

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = sync_operators.main([
                    "--data-dir", str(data_dir), "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Restored", out.getvalue())
            self.assertEqual(read_operator(data_dir, "abcd"), "OLDMGR")


if __name__ == "__main__":
    unittest.main()
