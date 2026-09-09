import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import quarantine_stale_templates
from tests.fixtures import make_data_dir

STALE_LINE = "wxyz|noverdue|Stale Template|n|200207021051|202001010000|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"
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


class TestBareDetect(unittest.TestCase):
    def test_saves_candidates_and_prints_count(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])
            work_dir = Path(tmp) / "work"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--work-dir", str(work_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("1 candidate(s) detected", out.getvalue())
            candidates_path = work_dir / "candidates.jsonl"
            self.assertTrue(candidates_path.is_file())
            self.assertIn("wxyz", candidates_path.read_text())
            # bare mode must not touch data-dir at all
            self.assertTrue((data_dir / "wxyz.set").exists())


class TestReportFlag(unittest.TestCase):
    def test_prints_full_report(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])
            work_dir = Path(tmp) / "work"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--work-dir", str(work_dir),
                    "--report",
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("SUMMARY", out.getvalue())
            self.assertIn("1 of 2 manual templates removed", out.getvalue())


class TestExecuteFlag(unittest.TestCase):
    def test_requires_prior_detect(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE], ["wxyz.set", "wxyz.selans"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp)
            work_dir = Path(tmp) / "work"

            err = io.StringIO()
            with self.assertRaises(SystemExit), redirect_stderr(err):
                quarantine_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--work-dir", str(work_dir),
                    "--execute",
                ])

            self.assertIn("No candidates file found", err.getvalue())
            self.assertFalse(quarantine_dir.exists())

    def test_quarantines_using_saved_candidates(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])
            work_dir = Path(tmp) / "work"

            with redirect_stdout(io.StringIO()):
                quarantine_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--work-dir", str(work_dir),
                ])

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--work-dir", str(work_dir),
                    "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Moved 2 file(s)", out.getvalue())
            self.assertFalse((data_dir / "wxyz.set").exists())
            self.assertTrue((data_dir / "abcd.set").exists())


class TestRestoreFlag(unittest.TestCase):
    def test_full_cycle_round_trips_cleanly(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])
            work_dir = Path(tmp) / "work"
            files_before = sorted(p.name for p in data_dir.iterdir())
            schedlist_before = sorted((data_dir / "schedlist").read_text().splitlines())

            with redirect_stdout(io.StringIO()):
                quarantine_stale_templates.main([
                    "--data-dir", str(data_dir), "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir), "--work-dir", str(work_dir),
                ])
                quarantine_stale_templates.main([
                    "--data-dir", str(data_dir), "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir), "--logs-hist-dir", str(hist_dir),
                    "--work-dir", str(work_dir), "--execute",
                ])

            run_dir = list(quarantine_dir.glob("templates_*"))[0]

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_stale_templates.main([
                    "--data-dir", str(data_dir), "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Restored", out.getvalue())
            self.assertEqual(sorted(p.name for p in data_dir.iterdir()), files_before)
            self.assertEqual(sorted((data_dir / "schedlist").read_text().splitlines()), schedlist_before)


if __name__ == "__main__":
    unittest.main()
