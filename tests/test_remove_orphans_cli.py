import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import remove_orphans
from rptsched_cleanup.quarantine import read_manifest
from tests.fixtures import make_data_dir


class TestDryRun(unittest.TestCase):
    def test_dry_run_reports_orphans_and_changes_nothing(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "abcd|noverdue|Known Template|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, ["abcd.set", "wxyz.set", "wxyz.user"])
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("wxyz", out.getvalue())
            self.assertFalse(quarantine_dir.exists())
            self.assertTrue((data_dir / "wxyz.set").exists())
            self.assertTrue((data_dir / "wxyz.user").exists())

    def test_missing_required_args_errors(self):
        with self.assertRaises(SystemExit):
            remove_orphans.main([])


class TestExecute(unittest.TestCase):
    def test_execute_moves_files_and_writes_manifest(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "abcd|noverdue|Known Template|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, ["abcd.set", "wxyz.set", "wxyz.user"])
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertFalse((data_dir / "wxyz.set").exists())
            self.assertFalse((data_dir / "wxyz.user").exists())
            self.assertTrue((data_dir / "abcd.set").exists())

            run_dirs = list(quarantine_dir.glob("orphans_*"))
            self.assertEqual(len(run_dirs), 1)
            run_dir = run_dirs[0]
            self.assertTrue((run_dir / "wxyz.set").is_file())
            self.assertTrue((run_dir / "wxyz.user").is_file())

            rows = read_manifest(run_dir)
            self.assertEqual(len(rows), 2)


class TestRestore(unittest.TestCase):
    def test_restore_moves_files_back(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "abcd|noverdue|Known Template|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, ["abcd.set", "wxyz.set", "wxyz.user"])
            quarantine_dir = Path(tmp) / "quarantine"

            with redirect_stdout(io.StringIO()):
                remove_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            run_dir = list(quarantine_dir.glob("orphans_*"))[0]

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertTrue((data_dir / "wxyz.set").is_file())
            self.assertTrue((data_dir / "wxyz.user").is_file())
            self.assertIn("restored", out.getvalue().lower())

    def test_restore_conflict_prints_error_and_exits_nonzero(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "abcd|noverdue|Known Template|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, ["abcd.set", "wxyz.set", "wxyz.user"])
            quarantine_dir = Path(tmp) / "quarantine"

            with redirect_stdout(io.StringIO()):
                remove_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            run_dir = list(quarantine_dir.glob("orphans_*"))[0]

            # Recreate a file at its original location so restore hits a conflict.
            (data_dir / "wxyz.set").write_text("conflicting content")

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = remove_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("wxyz.set", err.getvalue())
            self.assertIn("already exists", err.getvalue())


if __name__ == "__main__":
    unittest.main()
