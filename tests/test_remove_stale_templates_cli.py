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
ACTIVE_LINE = "abcd|noverdue|Active Template|n|200207021051|202001010000|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"


def _make_log_dirs(tmp, active_report_sources_and_descriptions=()):
    """
    Build --logs-report-dir/--logs-hist-dir, with a Logs/Report/
    "Finished report" line (timestamped "now", so it's always within the
    default 3yr window regardless of when tests run) for each
    (report_source, description) pair that should read as active.

    Always creates at least an empty placeholder file in each directory
    -- remove_stale_templates.py refuses to run against a log directory
    with zero files at all within the window (a wrong/unmounted path
    would otherwise silently look identical to "nothing is active"), and
    an empty file is enough to satisfy that check without asserting any
    activity.
    """
    report_dir = Path(tmp) / "Report"
    hist_dir = Path(tmp) / "Hist"
    report_dir.mkdir()
    hist_dir.mkdir()

    now = datetime.now()
    month_file = report_dir / (now.strftime("%Y%m") + ".log")
    with month_file.open("w") as f:
        for report_source, description in active_report_sources_and_descriptions:
            f.write('{} Finished report {}:"{}"\n'.format(now.strftime("%Y%m%d%H%M%S"), report_source, description))
    (hist_dir / (now.strftime("%Y%m") + ".hist")).touch()

    return report_dir, hist_dir


class TestDryRun(unittest.TestCase):
    def test_dry_run_reports_candidates_and_changes_nothing(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("wxyz", out.getvalue())
            self.assertNotIn("abcd", out.getvalue())
            # dry-run writes nothing at all, not even the activity-index
            # cache -- quarantine_dir must not be created
            self.assertFalse(quarantine_dir.exists())
            self.assertTrue((data_dir / "wxyz.set").exists())
            schedlist_text = (data_dir / "schedlist").read_text()
            self.assertIn("wxyz", schedlist_text)
            self.assertIn("abcd", schedlist_text)

    def test_missing_required_args_errors(self):
        with self.assertRaises(SystemExit):
            remove_stale_templates.main([])

    def test_missing_log_dirs_errors_outside_restore(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE], ["wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            with redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    remove_stale_templates.main([
                        "--data-dir", str(data_dir),
                        "--quarantine-dir", str(quarantine_dir),
                    ])

    def test_empty_logs_report_dir_refuses_to_run(self):
        # A wrong/unmounted --logs-report-dir globs to zero files rather
        # than erroring on its own -- must be caught explicitly, since
        # the alternative is silently treating every manual template as
        # inactive (the same failure shape as the original incident).
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE], ["wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            empty_report_dir = Path(tmp) / "EmptyReport"
            empty_report_dir.mkdir()
            _, hist_dir = _make_log_dirs(tmp)

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(empty_report_dir),
                    "--logs-hist-dir", str(hist_dir),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn(str(empty_report_dir), err.getvalue())

    def test_empty_logs_hist_dir_refuses_to_run(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE], ["wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, _ = _make_log_dirs(tmp)
            empty_hist_dir = Path(tmp) / "EmptyHist"
            empty_hist_dir.mkdir()

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(empty_hist_dir),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn(str(empty_hist_dir), err.getvalue())

    def test_nonexistent_logs_dir_refuses_to_run_same_as_empty(self):
        # A typo'd path that doesn't exist at all behaves identically to
        # an existing-but-empty one (Path.glob on a missing dir just
        # yields nothing) -- confirm that's caught too, not just the
        # exists-but-empty case.
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE], ["wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            _, hist_dir = _make_log_dirs(tmp)
            nonexistent_report_dir = Path(tmp) / "does_not_exist_at_all"

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(nonexistent_report_dir),
                    "--logs-hist-dir", str(hist_dir),
                ])

            self.assertEqual(exit_code, 1)


class TestExecute(unittest.TestCase):
    def test_execute_moves_files_writes_manifest_and_rewrites_schedlist(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
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
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])
            schedlist_bytes_before = (data_dir / "schedlist").read_bytes()

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertTrue((data_dir / "abcd.set").exists())
            schedlist_lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(schedlist_lines, [ACTIVE_LINE])
            self.assertEqual((data_dir / "schedlist").read_bytes(), schedlist_bytes_before)
            # --execute is allowed side effects (unlike dry-run) -- building
            # the activity index cache may create quarantine_dir even with
            # zero candidates, but no run subfolder should exist since
            # nothing was actually quarantined.
            self.assertEqual(list(quarantine_dir.glob("templates_*")), [])
            self.assertIn("no stale template", out.getvalue().lower())

    def test_execute_aborts_before_schedlist_rewrite_on_move_failure(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE], ["wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp)

            with patch("rptsched_lib.quarantine.shutil.move", side_effect=OSError("simulated failure")):
                err = io.StringIO()
                with redirect_stdout(io.StringIO()), redirect_stderr(err):
                    exit_code = remove_stale_templates.main([
                        "--data-dir", str(data_dir),
                        "--quarantine-dir", str(quarantine_dir),
                        "--logs-report-dir", str(report_dir),
                        "--logs-hist-dir", str(hist_dir),
                        "--execute",
                    ])

            self.assertEqual(exit_code, 1)
            self.assertIn("wxyz.set", err.getvalue())
            # schedlist must be untouched — the failed move happens before any schedlist rewrite
            schedlist_lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(schedlist_lines, [STALE_LINE])
            self.assertTrue((data_dir / "wxyz.set").exists())

    def test_exclude_owner_precise_excludes_exact_match_only(self):
        with TemporaryDirectory() as tmp:
            acq1_line = "aaaa|noverdue|ACQ1 Template|n|200207021051|202001010000|ACQ1||||||0|3||0|$<library_notice:c>|ENGLISH|"
            acq10_line = "bbbb|noverdue|ACQ10 Template|n|200207021051|202001010000|ACQ10||||||0|3||0|$<library_notice:c>|ENGLISH|"
            data_dir = make_data_dir(tmp, [acq1_line, acq10_line], ["aaaa.set", "bbbb.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp)

            out = io.StringIO()
            with redirect_stdout(out):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--exclude-owner", "ACQ1",
                ])

            self.assertNotIn("aaaa", out.getvalue())
            self.assertIn("bbbb", out.getvalue())

    def test_exclude_owner_regex_matches_broadly(self):
        with TemporaryDirectory() as tmp:
            acqhq_line = "aaaa|noverdue|ACQHQ Template|n|200207021051|202001010000|ACQHQ||||||0|3||0|$<library_notice:c>|ENGLISH|"
            data_dir = make_data_dir(tmp, [acqhq_line], ["aaaa.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp)

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--exclude-owner-regex", "acq",
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("0 stale template", out.getvalue())

    def test_years_override_changes_candidate_set(self):
        with TemporaryDirectory() as tmp:
            # created 2yr before "now": protected by the recency floor at
            # years=3, a candidate at years=1. No log activity either way
            # -- isolates the --years-sensitive recency-floor path.
            two_years_ago = datetime.now().replace(year=datetime.now().year - 2)
            created = two_years_ago.strftime("%Y%m%d%H%M")
            recent_but_old_line = "mmmm|noverdue|Middling|n|{}|202001010000|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|".format(created)
            data_dir = make_data_dir(tmp, [recent_but_old_line], ["mmmm.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp)

            out = io.StringIO()
            with redirect_stdout(out):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                ])
            self.assertNotIn("mmmm", out.getvalue())

            out = io.StringIO()
            with redirect_stdout(out):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--years", "1",
                ])
            self.assertIn("mmmm", out.getvalue())


class TestRestore(unittest.TestCase):
    def test_restore_moves_files_back_and_reinserts_schedlist_line(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])

            with redirect_stdout(io.StringIO()):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
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
            report_dir, hist_dir = _make_log_dirs(tmp)

            with redirect_stdout(io.StringIO()):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
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
            report_dir, hist_dir = _make_log_dirs(tmp)

            with patch("rptsched_lib.quarantine.shutil.move", side_effect=OSError("simulated failure")):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    exit_code = remove_stale_templates.main([
                        "--data-dir", str(data_dir),
                        "--quarantine-dir", str(quarantine_dir),
                        "--logs-report-dir", str(report_dir),
                        "--logs-hist-dir", str(hist_dir),
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
            report_dir, hist_dir = _make_log_dirs(tmp)

            with redirect_stdout(io.StringIO()):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
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
