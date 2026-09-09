import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from composables import execute_stale_templates
from tests.fixtures import make_rptsched_dir

STALE_LINE = "wxyz|noverdue|Stale Template|n|200207021051|202001010000|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"
ANOTHER_STALE_LINE = "qmzk|noverdue|Another Stale One|n|200207021051|202001010000|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"
ACTIVE_LINE = "abcd|noverdue|Active Template|n|200207021051|202001010000|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"


def _make_log_dirs(tmp, active_report_sources_and_descriptions=()):
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


def _reviewed_file_for(tmp, template_id, raw_line, filenames):
    record = {
        "schema_version": 1,
        "id": template_id,
        "raw_line": raw_line,
        "filenames": filenames,
    }
    path = Path(tmp) / "reviewed.jsonl"
    path.write_text(json.dumps(record) + "\n")
    return path


class TestExecute(unittest.TestCase):
    def test_moves_files_and_rewrites_schedlist(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])
            reviewed_file = _reviewed_file_for(tmp, "wxyz", STALE_LINE, ["wxyz.set", "wxyz.selans"])

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = execute_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Moved 2 file(s)", out.getvalue())
            self.assertFalse((rptsched_dir / "wxyz.set").exists())
            self.assertFalse((rptsched_dir / "wxyz.selans").exists())
            self.assertTrue((rptsched_dir / "abcd.set").exists())
            remaining_ids = {line.split("|")[0] for line in (rptsched_dir / "schedlist").read_text().splitlines() if line.strip()}
            self.assertEqual(remaining_ids, {"abcd"})

    def test_aborts_when_schedlist_line_changed_since_review(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set", "wxyz.selans"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp)
            # Reviewed file captures the OLD raw_line, before schedlist changed.
            reviewed_file = _reviewed_file_for(tmp, "wxyz", STALE_LINE, ["wxyz.set", "wxyz.selans"])

            # Simulate drift: owner changed in schedlist after review.
            changed_line = STALE_LINE.replace("SOMEMGR", "OTHERMGR")
            (rptsched_dir / "schedlist").write_text(changed_line + "\n")

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = execute_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("Refusing to proceed", err.getvalue())
            self.assertTrue((rptsched_dir / "wxyz.set").exists())
            self.assertFalse(quarantine_dir.exists())

    def test_aborts_when_reviewed_id_no_longer_a_candidate(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set", "wxyz.selans"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Stale Template")])
            reviewed_file = _reviewed_file_for(tmp, "wxyz", STALE_LINE, ["wxyz.set", "wxyz.selans"])

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = execute_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("no longer a stale candidate", err.getvalue())
            self.assertTrue((rptsched_dir / "wxyz.set").exists())

    def test_exclude_report_source_flag_participates_in_fresh_redetect(self):
        # A reviewed file that was captured without --exclude-report-source
        # but executed with it should abort, exactly like any other
        # drift between review and execute -- proving the flag actually
        # feeds the pre-mutation re-detect, not just the initial detect.
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set", "wxyz.selans"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp)
            reviewed_file = _reviewed_file_for(tmp, "wxyz", STALE_LINE, ["wxyz.set", "wxyz.selans"])

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = execute_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--exclude-report-source", "noverdue",
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("no longer a stale candidate", err.getvalue())
            self.assertTrue((rptsched_dir / "wxyz.set").exists())
            self.assertFalse(quarantine_dir.exists())

    def test_ignores_new_candidate_not_in_reviewed_file(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(
                tmp, [STALE_LINE, ANOTHER_STALE_LINE], ["wxyz.set", "wxyz.selans", "qmzk.set"],
            )
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp)
            # Only wxyz was reviewed; qmzk is a genuine stale candidate too
            # but wasn't part of what was signed off on.
            reviewed_file = _reviewed_file_for(tmp, "wxyz", STALE_LINE, ["wxyz.set", "wxyz.selans"])

            with redirect_stdout(io.StringIO()):
                exit_code = execute_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertFalse((rptsched_dir / "wxyz.set").exists())
            self.assertTrue((rptsched_dir / "qmzk.set").exists())
            remaining_ids = {line.split("|")[0] for line in (rptsched_dir / "schedlist").read_text().splitlines() if line.strip()}
            self.assertEqual(remaining_ids, {"qmzk"})

    def test_empty_reviewed_file_does_nothing(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp)
            reviewed_file = Path(tmp) / "empty.jsonl"
            reviewed_file.write_text("")

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = execute_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("nothing to do", out.getvalue())
            self.assertFalse(quarantine_dir.exists())


class TestRestore(unittest.TestCase):
    def test_execute_then_restore_round_trips_cleanly(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])
            reviewed_file = _reviewed_file_for(tmp, "wxyz", STALE_LINE, ["wxyz.set", "wxyz.selans"])

            files_before = sorted(p.name for p in rptsched_dir.iterdir() if p.name != "schedlist")
            schedlist_before = sorted((rptsched_dir / "schedlist").read_text().splitlines())

            with redirect_stdout(io.StringIO()):
                exit_code = execute_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                ])
            self.assertEqual(exit_code, 0)

            run_dir = list(quarantine_dir.glob("templates_*"))[0]
            self.assertTrue((run_dir / "removed_schedlist_lines.txt").is_file())
            self.assertTrue((run_dir / "manifest.csv").is_file())

            with redirect_stdout(io.StringIO()):
                exit_code = execute_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])
            self.assertEqual(exit_code, 0)

            files_after = sorted(p.name for p in rptsched_dir.iterdir() if p.name != "schedlist")
            schedlist_after = sorted((rptsched_dir / "schedlist").read_text().splitlines())
            self.assertEqual(files_before, files_after)
            self.assertEqual(schedlist_before, schedlist_after)


if __name__ == "__main__":
    unittest.main()
