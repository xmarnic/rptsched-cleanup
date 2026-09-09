import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import quarantine_orphans
from tests.fixtures import make_rptsched_dir

KNOWN_LINE = "abcd|noverdue|Known Template|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"


class TestBareDetect(unittest.TestCase):
    def test_saves_candidates_and_prints_count(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set", "wxyz.user"])
            data_dir = Path(tmp) / "work"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_orphans.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--data-dir", str(data_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("1 candidate(s) detected", out.getvalue())
            self.assertIn("wxyz", (data_dir / "candidates.jsonl").read_text())
            self.assertTrue((rptsched_dir / "wxyz.set").exists())


class TestReportFlag(unittest.TestCase):
    def test_prints_full_report(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set", "wxyz.user"])
            data_dir = Path(tmp) / "work"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_orphans.main([
                    "--rptsched-dir", str(rptsched_dir), "--data-dir", str(data_dir), "--report",
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("1 orphan id(s), 2 file(s)", out.getvalue())


class TestExecuteFlag(unittest.TestCase):
    def test_requires_prior_detect(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            data_dir = Path(tmp) / "work"

            err = io.StringIO()
            with self.assertRaises(SystemExit), redirect_stderr(err):
                quarantine_orphans.main([
                    "--rptsched-dir", str(rptsched_dir), "--quarantine-dir", str(quarantine_dir),
                    "--data-dir", str(data_dir), "--execute",
                ])

            self.assertIn("No candidates file found", err.getvalue())
            self.assertFalse(quarantine_dir.exists())

    def test_quarantines_using_saved_candidates(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set", "wxyz.user"])
            quarantine_dir = Path(tmp) / "quarantine"
            data_dir = Path(tmp) / "work"

            with redirect_stdout(io.StringIO()):
                quarantine_orphans.main(["--rptsched-dir", str(rptsched_dir), "--data-dir", str(data_dir)])

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_orphans.main([
                    "--rptsched-dir", str(rptsched_dir), "--quarantine-dir", str(quarantine_dir),
                    "--data-dir", str(data_dir), "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Moved 2 file(s)", out.getvalue())
            self.assertFalse((rptsched_dir / "wxyz.set").exists())
            self.assertTrue((rptsched_dir / "abcd.set").exists())


class TestRestoreFlag(unittest.TestCase):
    def test_full_cycle_round_trips_cleanly(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set", "wxyz.user"])
            quarantine_dir = Path(tmp) / "quarantine"
            data_dir = Path(tmp) / "work"
            files_before = sorted(p.name for p in rptsched_dir.iterdir())

            with redirect_stdout(io.StringIO()):
                quarantine_orphans.main(["--rptsched-dir", str(rptsched_dir), "--data-dir", str(data_dir)])
                quarantine_orphans.main([
                    "--rptsched-dir", str(rptsched_dir), "--quarantine-dir", str(quarantine_dir),
                    "--data-dir", str(data_dir), "--execute",
                ])

            run_dir = list(quarantine_dir.glob("orphans_*"))[0]

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_orphans.main([
                    "--rptsched-dir", str(rptsched_dir), "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Restored", out.getvalue())
            self.assertEqual(sorted(p.name for p in rptsched_dir.iterdir()), files_before)


def _make_unicorn_rptsched_dir(tmp, schedlist_lines, extra_files):
    root = Path(tmp) / "Unicorn"
    rptsched_dir = root / "Rptsched"
    rptsched_dir.mkdir(parents=True)
    with (rptsched_dir / "schedlist").open("w") as f:
        for line in schedlist_lines:
            f.write(line + "\n")
    for filename in extra_files:
        (rptsched_dir / filename).write_text("placeholder")
    return root


class TestUnicornRoot(unittest.TestCase):
    def test_flag_derives_rptsched_dir(self):
        with TemporaryDirectory() as tmp:
            root = _make_unicorn_rptsched_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set"])
            data_dir = Path(tmp) / "work"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_orphans.main(["--unicorn-root", str(root), "--data-dir", str(data_dir)])

            self.assertEqual(exit_code, 0)
            self.assertIn("1 candidate(s) detected", out.getvalue())

    def test_env_var_derives_rptsched_dir(self):
        with TemporaryDirectory() as tmp:
            root = _make_unicorn_rptsched_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set"])
            data_dir = Path(tmp) / "work"

            out = io.StringIO()
            with patch.dict(os.environ, {"RPTSCHED_UNICORN_ROOT": str(root)}):
                with redirect_stdout(out):
                    exit_code = quarantine_orphans.main(["--data-dir", str(data_dir)])

            self.assertEqual(exit_code, 0)
            self.assertIn("1 candidate(s) detected", out.getvalue())

    def test_missing_rptsched_dir_and_unicorn_root_errors(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RPTSCHED_UNICORN_ROOT", None)
            with self.assertRaises(SystemExit):
                with redirect_stderr(io.StringIO()):
                    quarantine_orphans.main([])


if __name__ == "__main__":
    unittest.main()
