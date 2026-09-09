import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import quarantine_stale_templates
from tests.fixtures import make_rptsched_dir

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
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])
            data_dir = Path(tmp) / "work"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--data-dir", str(data_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("1 candidate(s) detected", out.getvalue())
            candidates_path = data_dir / "candidates.jsonl"
            self.assertTrue(candidates_path.is_file())
            self.assertIn("wxyz", candidates_path.read_text())
            # bare mode must not touch rptsched-dir at all
            self.assertTrue((rptsched_dir / "wxyz.set").exists())

    def test_exclude_report_source_flag_is_forwarded_to_detect(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set", "wxyz.selans"])
            report_dir, hist_dir = _make_log_dirs(tmp)
            data_dir = Path(tmp) / "work"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--data-dir", str(data_dir),
                    "--exclude-report-source", "noverdue",
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("0 candidate(s) detected", out.getvalue())


class TestReportFlag(unittest.TestCase):
    def test_prints_full_report(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])
            data_dir = Path(tmp) / "work"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--data-dir", str(data_dir),
                    "--report",
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("SUMMARY", out.getvalue())
            self.assertIn("1 of 2 manual templates removed", out.getvalue())


class TestExecuteFlag(unittest.TestCase):
    def test_requires_prior_detect(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set", "wxyz.selans"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp)
            data_dir = Path(tmp) / "work"

            err = io.StringIO()
            with self.assertRaises(SystemExit), redirect_stderr(err):
                quarantine_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--data-dir", str(data_dir),
                    "--execute",
                ])

            self.assertIn("No candidates file found", err.getvalue())
            self.assertFalse(quarantine_dir.exists())

    def test_quarantines_using_saved_candidates(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])
            data_dir = Path(tmp) / "work"

            with redirect_stdout(io.StringIO()):
                quarantine_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--data-dir", str(data_dir),
                ])

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--data-dir", str(data_dir),
                    "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Moved 2 file(s)", out.getvalue())
            self.assertFalse((rptsched_dir / "wxyz.set").exists())
            self.assertTrue((rptsched_dir / "abcd.set").exists())


class TestRestoreFlag(unittest.TestCase):
    def test_full_cycle_round_trips_cleanly(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])
            data_dir = Path(tmp) / "work"
            files_before = sorted(p.name for p in rptsched_dir.iterdir())
            schedlist_before = sorted((rptsched_dir / "schedlist").read_text().splitlines())

            with redirect_stdout(io.StringIO()):
                quarantine_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir), "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir), "--data-dir", str(data_dir),
                ])
                quarantine_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir), "--quarantine-dir", str(quarantine_dir),
                    "--logs-report-dir", str(report_dir), "--logs-hist-dir", str(hist_dir),
                    "--data-dir", str(data_dir), "--execute",
                ])

            run_dir = list(quarantine_dir.glob("templates_*"))[0]

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir), "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Restored", out.getvalue())
            self.assertEqual(sorted(p.name for p in rptsched_dir.iterdir()), files_before)
            self.assertEqual(sorted((rptsched_dir / "schedlist").read_text().splitlines()), schedlist_before)


def _make_unicorn_root(tmp, schedlist_lines, extra_files, active_report_sources_and_descriptions=()):
    root = Path(tmp) / "Unicorn"
    rptsched_dir = root / "Rptsched"
    rptsched_dir.mkdir(parents=True)
    with (rptsched_dir / "schedlist").open("w") as f:
        for line in schedlist_lines:
            f.write(line + "\n")
    for filename in extra_files:
        (rptsched_dir / filename).write_text("placeholder")

    report_dir, hist_dir = _make_log_dirs(tmp, active_report_sources_and_descriptions)
    (root / "Logs" / "Report").mkdir(parents=True)
    (root / "Logs" / "Hist").mkdir(parents=True)
    for f in report_dir.iterdir():
        (root / "Logs" / "Report" / f.name).write_text(f.read_text())
    for f in hist_dir.iterdir():
        (root / "Logs" / "Hist" / f.name).write_text(f.read_text())
    return root, rptsched_dir


class TestUnicornRoot(unittest.TestCase):
    def test_flag_derives_all_three_paths(self):
        with TemporaryDirectory() as tmp:
            root, rptsched_dir = _make_unicorn_root(tmp, [STALE_LINE], ["wxyz.set"])
            data_dir = Path(tmp) / "work"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_stale_templates.main([
                    "--unicorn-root", str(root),
                    "--data-dir", str(data_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("1 candidate(s) detected", out.getvalue())

    def test_env_var_derives_all_three_paths(self):
        with TemporaryDirectory() as tmp:
            root, rptsched_dir = _make_unicorn_root(tmp, [STALE_LINE], ["wxyz.set"])
            data_dir = Path(tmp) / "work"

            out = io.StringIO()
            with patch.dict(os.environ, {"RPTSCHED_UNICORN_ROOT": str(root)}):
                with redirect_stdout(out):
                    exit_code = quarantine_stale_templates.main(["--data-dir", str(data_dir)])

            self.assertEqual(exit_code, 0)
            self.assertIn("1 candidate(s) detected", out.getvalue())

    def test_explicit_rptsched_dir_overrides_derived_value(self):
        with TemporaryDirectory() as tmp:
            root, unicorn_rptsched_dir = _make_unicorn_root(tmp, [ACTIVE_LINE], ["abcd.set"])
            override_rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set"])
            data_dir = Path(tmp) / "work"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = quarantine_stale_templates.main([
                    "--unicorn-root", str(root),
                    "--rptsched-dir", str(override_rptsched_dir),
                    "--data-dir", str(data_dir),
                ])

            self.assertEqual(exit_code, 0)
            # candidate came from the override dir (wxyz), not the
            # unicorn-root-derived one (which only has abcd, active)
            self.assertIn("wxyz", (data_dir / "candidates.jsonl").read_text())

    def test_missing_rptsched_dir_and_unicorn_root_errors(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RPTSCHED_UNICORN_ROOT", None)
            with self.assertRaises(SystemExit):
                with redirect_stderr(io.StringIO()):
                    quarantine_stale_templates.main([])


if __name__ == "__main__":
    unittest.main()
