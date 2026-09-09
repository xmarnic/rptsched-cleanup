import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from composables import detect_stale_templates
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


class TestDetectStaleTemplatesCli(unittest.TestCase):
    def test_emits_one_jsonl_record_per_stale_candidate(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])
            cache_path = Path(tmp) / "cache.json"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = detect_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--index-cache-path", str(cache_path),
                ])

            self.assertEqual(exit_code, 0)
            lines = [line for line in out.getvalue().splitlines() if line.strip()]
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["id"], "wxyz")
            self.assertEqual(record["report_source"], "noverdue")
            self.assertEqual(record["owner"], "SOMEMGR")
            self.assertEqual(record["raw_line"], STALE_LINE)
            self.assertEqual(sorted(record["filenames"]), ["wxyz.selans", "wxyz.set"])
            self.assertIn("schema_version", record)

    def test_last_run_is_never_included_in_the_record(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set", "wxyz.selans"])
            report_dir, hist_dir = _make_log_dirs(tmp)
            cache_path = Path(tmp) / "cache.json"

            out = io.StringIO()
            with redirect_stdout(out):
                detect_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--index-cache-path", str(cache_path),
                ])

            record = json.loads(out.getvalue().splitlines()[0])
            self.assertNotIn("last_run", record)

    def test_does_not_modify_rptsched_dir(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set", "wxyz.selans"])
            report_dir, hist_dir = _make_log_dirs(tmp)
            cache_path = Path(tmp) / "cache.json"
            schedlist_before = (rptsched_dir / "schedlist").read_text()
            files_before = sorted(p.name for p in rptsched_dir.iterdir())

            with redirect_stdout(io.StringIO()):
                detect_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--index-cache-path", str(cache_path),
                ])

            self.assertEqual((rptsched_dir / "schedlist").read_text(), schedlist_before)
            self.assertEqual(sorted(p.name for p in rptsched_dir.iterdir()), files_before)

    def test_writes_cache_file_at_given_path(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set", "wxyz.selans"])
            report_dir, hist_dir = _make_log_dirs(tmp)
            cache_path = Path(tmp) / "nested" / "cache.json"

            with redirect_stdout(io.StringIO()):
                exit_code = detect_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--index-cache-path", str(cache_path),
                ])

            self.assertEqual(exit_code, 0)
            self.assertTrue(cache_path.is_file())

    def test_no_candidates_emits_empty_stream(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [ACTIVE_LINE], ["abcd.set"])
            report_dir, hist_dir = _make_log_dirs(tmp, [("noverdue", "Active Template")])
            cache_path = Path(tmp) / "cache.json"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = detect_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--index-cache-path", str(cache_path),
                ])

            self.assertEqual(exit_code, 0)
            self.assertEqual(out.getvalue().strip(), "")

    def test_refuses_empty_logs_report_dir(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [STALE_LINE], ["wxyz.set"])
            empty_report_dir = Path(tmp) / "EmptyReport"
            empty_report_dir.mkdir()
            _, hist_dir = _make_log_dirs(tmp)
            cache_path = Path(tmp) / "cache.json"

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = detect_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--logs-report-dir", str(empty_report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--index-cache-path", str(cache_path),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("Refusing to proceed", err.getvalue())


if __name__ == "__main__":
    unittest.main()
