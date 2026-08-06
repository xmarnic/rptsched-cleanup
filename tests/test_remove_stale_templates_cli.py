import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import remove_stale_templates
from rptsched_lib.quarantine import read_manifest
from tests.fixtures import make_data_dir

STALE_LINE = "wxyz|noverdue|Stale Template|n|200207021051|202001010000|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"
ACTIVE_LINE = "abcd|noverdue|Active Template|n|200207021051|202601010000|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"


class TestDryRun(unittest.TestCase):
    def test_dry_run_reports_candidates_and_changes_nothing(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("wxyz", out.getvalue())
            self.assertNotIn("abcd", out.getvalue())
            self.assertFalse(quarantine_dir.exists())
            self.assertTrue((data_dir / "wxyz.set").exists())
            schedlist_text = (data_dir / "schedlist").read_text()
            self.assertIn("wxyz", schedlist_text)
            self.assertIn("abcd", schedlist_text)

    def test_missing_required_args_errors(self):
        with self.assertRaises(SystemExit):
            remove_stale_templates.main([])


class TestExecute(unittest.TestCase):
    def test_execute_moves_files_writes_manifest_and_rewrites_schedlist(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertFalse((data_dir / "wxyz.set").exists())
            self.assertFalse((data_dir / "wxyz.selans").exists())
            self.assertTrue((data_dir / "abcd.set").exists())

            schedlist_lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(schedlist_lines, [ACTIVE_LINE])

            run_dirs = list(quarantine_dir.glob("templates_*"))
            self.assertEqual(len(run_dirs), 1)
            run_dir = run_dirs[0]

            rows = read_manifest(run_dir)
            self.assertEqual(len(rows), 2)

            removed_text = (run_dir / "removed_schedlist_lines.txt").read_text().splitlines()
            self.assertEqual(removed_text, [STALE_LINE])

    def test_execute_with_no_candidates_touches_nothing(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [ACTIVE_LINE], ["abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            schedlist_bytes_before = (data_dir / "schedlist").read_bytes()

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertTrue((data_dir / "abcd.set").exists())
            schedlist_lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(schedlist_lines, [ACTIVE_LINE])
            self.assertEqual((data_dir / "schedlist").read_bytes(), schedlist_bytes_before)
            self.assertFalse(quarantine_dir.exists())
            self.assertIn("no stale template", out.getvalue().lower())

    def test_execute_aborts_before_schedlist_rewrite_on_move_failure(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE], ["wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            with patch("rptsched_lib.quarantine.shutil.move", side_effect=OSError("simulated failure")):
                err = io.StringIO()
                with redirect_stdout(io.StringIO()), redirect_stderr(err):
                    exit_code = remove_stale_templates.main([
                        "--data-dir", str(data_dir),
                        "--quarantine-dir", str(quarantine_dir),
                        "--execute",
                    ])

            self.assertEqual(exit_code, 1)
            self.assertIn("wxyz.set", err.getvalue())
            # schedlist must be untouched — the failed move happens before any schedlist rewrite
            schedlist_lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(schedlist_lines, [STALE_LINE])
            self.assertTrue((data_dir / "wxyz.set").exists())

    def test_years_override_changes_candidate_set(self):
        with TemporaryDirectory() as tmp:
            # last_run ~1.5 years before "now" — not stale at years=3, stale at years=1
            recent_but_old_line = "mmmm|noverdue|Middling|n|200207021051|202501010000|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"
            data_dir = make_data_dir(tmp, [recent_but_old_line], ["mmmm.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--years", "1",
                ])

            self.assertIn("mmmm", out.getvalue())


class TestRestore(unittest.TestCase):
    def test_restore_moves_files_back_and_reinserts_schedlist_line(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            with redirect_stdout(io.StringIO()):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            run_dir = list(quarantine_dir.glob("templates_*"))[0]

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertTrue((data_dir / "wxyz.set").is_file())
            self.assertTrue((data_dir / "wxyz.selans").is_file())
            self.assertIn("restored", out.getvalue().lower())
            self.assertIn("re-inserted", out.getvalue().lower())

            schedlist_lines = sorted((data_dir / "schedlist").read_text().splitlines())
            self.assertEqual(schedlist_lines, sorted([STALE_LINE, ACTIVE_LINE]))

    def test_second_restore_is_idempotent(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE], ["wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            with redirect_stdout(io.StringIO()):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])
            run_dir = list(quarantine_dir.glob("templates_*"))[0]

            with redirect_stdout(io.StringIO()):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Restored 0 file(s), skipped 1", out.getvalue())
            self.assertIn("Re-inserted 0 schedlist line(s), skipped 1", out.getvalue())
            schedlist_lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(schedlist_lines, [STALE_LINE])  # not duplicated

    def test_restore_after_failed_execute_handles_missing_removed_lines_file(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE], ["wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            with patch("rptsched_lib.quarantine.shutil.move", side_effect=OSError("simulated failure")):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    exit_code = remove_stale_templates.main([
                        "--data-dir", str(data_dir),
                        "--quarantine-dir", str(quarantine_dir),
                        "--execute",
                    ])
            self.assertEqual(exit_code, 1)

            run_dir = list(quarantine_dir.glob("templates_*"))[0]
            self.assertTrue((run_dir / "manifest.csv").exists())
            self.assertFalse((run_dir / "removed_schedlist_lines.txt").exists())

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("restored", out.getvalue().lower())
            self.assertIn("Re-inserted 0 schedlist line(s)", out.getvalue())

    def test_restore_conflict_prints_error_exits_nonzero_and_skips_schedlist_phase(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE], ["wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            with redirect_stdout(io.StringIO()):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])
            run_dir = list(quarantine_dir.glob("templates_*"))[0]

            # Recreate a file at its original location so restore hits a conflict.
            (data_dir / "wxyz.set").write_text("conflicting content")

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("wxyz.set", err.getvalue())
            self.assertIn("already exists", err.getvalue())
            # Phase 2 (schedlist) must not have run since Phase 1 failed
            schedlist_lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(schedlist_lines, [])


if __name__ == "__main__":
    unittest.main()
