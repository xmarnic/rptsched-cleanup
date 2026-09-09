import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from composables import build_activity_index_cache


def _log_dirs_with_placeholder(tmp):
    report_dir = Path(tmp) / "Report"
    hist_dir = Path(tmp) / "Hist"
    report_dir.mkdir()
    hist_dir.mkdir()
    now = datetime.now()
    (report_dir / (now.strftime("%Y%m") + ".log")).touch()
    (hist_dir / (now.strftime("%Y%m") + ".hist")).touch()
    return report_dir, hist_dir


class TestBuildActivityIndexCacheCli(unittest.TestCase):
    def test_writes_cache_file(self):
        with TemporaryDirectory() as tmp:
            report_dir, hist_dir = _log_dirs_with_placeholder(tmp)
            cache_path = Path(tmp) / "cache.json"

            with redirect_stdout(io.StringIO()):
                exit_code = build_activity_index_cache.main([
                    "--logs-report-dir", str(report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--index-cache-path", str(cache_path),
                ])

            self.assertEqual(exit_code, 0)
            self.assertTrue(cache_path.is_file())

    def test_second_run_reuses_cache_without_error(self):
        with TemporaryDirectory() as tmp:
            report_dir, hist_dir = _log_dirs_with_placeholder(tmp)
            cache_path = Path(tmp) / "cache.json"
            argv = [
                "--logs-report-dir", str(report_dir),
                "--logs-hist-dir", str(hist_dir),
                "--index-cache-path", str(cache_path),
            ]

            with redirect_stdout(io.StringIO()):
                build_activity_index_cache.main(argv)
                exit_code = build_activity_index_cache.main(argv)

            self.assertEqual(exit_code, 0)

    def test_refuses_empty_logs_report_dir(self):
        with TemporaryDirectory() as tmp:
            empty_report_dir = Path(tmp) / "EmptyReport"
            empty_report_dir.mkdir()
            _, hist_dir = _log_dirs_with_placeholder(tmp)
            cache_path = Path(tmp) / "cache.json"

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = build_activity_index_cache.main([
                    "--logs-report-dir", str(empty_report_dir),
                    "--logs-hist-dir", str(hist_dir),
                    "--index-cache-path", str(cache_path),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("Refusing to proceed", err.getvalue())
            self.assertFalse(cache_path.exists())


if __name__ == "__main__":
    unittest.main()
