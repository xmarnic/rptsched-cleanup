import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import quarantine_orphans
from tests.fixtures import make_data_dir

KNOWN_LINE = "abcd|noverdue|Known Template|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"


class TestBareDetect(unittest.TestCase):
    def test_saves_candidates_and_prints_count(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set", "wxyz.user"])
            work_dir = Path(tmp) / "work"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_orphans.main([
                    "--data-dir", str(data_dir),
                    "--work-dir", str(work_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("1 candidate(s) detected", out.getvalue())
            self.assertIn("wxyz", (work_dir / "candidates.jsonl").read_text())
            self.assertTrue((data_dir / "wxyz.set").exists())


class TestReportFlag(unittest.TestCase):
    def test_prints_full_report(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set", "wxyz.user"])
            work_dir = Path(tmp) / "work"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_orphans.main([
                    "--data-dir", str(data_dir), "--work-dir", str(work_dir), "--report",
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("1 orphan id(s), 2 file(s)", out.getvalue())


class TestExecuteFlag(unittest.TestCase):
    def test_requires_prior_detect(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            work_dir = Path(tmp) / "work"

            err = io.StringIO()
            with self.assertRaises(SystemExit), redirect_stderr(err):
                quarantine_orphans.main([
                    "--data-dir", str(data_dir), "--quarantine-dir", str(quarantine_dir),
                    "--work-dir", str(work_dir), "--execute",
                ])

            self.assertIn("No candidates file found", err.getvalue())
            self.assertFalse(quarantine_dir.exists())

    def test_quarantines_using_saved_candidates(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set", "wxyz.user"])
            quarantine_dir = Path(tmp) / "quarantine"
            work_dir = Path(tmp) / "work"

            with redirect_stdout(io.StringIO()):
                quarantine_orphans.main(["--data-dir", str(data_dir), "--work-dir", str(work_dir)])

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_orphans.main([
                    "--data-dir", str(data_dir), "--quarantine-dir", str(quarantine_dir),
                    "--work-dir", str(work_dir), "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Moved 2 file(s)", out.getvalue())
            self.assertFalse((data_dir / "wxyz.set").exists())
            self.assertTrue((data_dir / "abcd.set").exists())


class TestRestoreFlag(unittest.TestCase):
    def test_full_cycle_round_trips_cleanly(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set", "wxyz.user"])
            quarantine_dir = Path(tmp) / "quarantine"
            work_dir = Path(tmp) / "work"
            files_before = sorted(p.name for p in data_dir.iterdir())

            with redirect_stdout(io.StringIO()):
                quarantine_orphans.main(["--data-dir", str(data_dir), "--work-dir", str(work_dir)])
                quarantine_orphans.main([
                    "--data-dir", str(data_dir), "--quarantine-dir", str(quarantine_dir),
                    "--work-dir", str(work_dir), "--execute",
                ])

            run_dir = list(quarantine_dir.glob("orphans_*"))[0]

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_orphans.main([
                    "--data-dir", str(data_dir), "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Restored", out.getvalue())
            self.assertEqual(sorted(p.name for p in data_dir.iterdir()), files_before)


if __name__ == "__main__":
    unittest.main()
