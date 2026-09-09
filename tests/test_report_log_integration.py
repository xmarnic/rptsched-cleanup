import unittest
from datetime import datetime
from pathlib import Path

from rptsched_lib.report_log import scan_report_logs

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGS_REPORT_DIR = REPO_ROOT / "logs" / "Report"


@unittest.skipUnless(LOGS_REPORT_DIR.is_dir(), "local logs/Report/ pull not present")
class TestScanReportLogsAgainstRealData(unittest.TestCase):
    def test_finds_daily_consolidate_report_recently_active(self):
        # consolidate ("$<consolidate_daily_logs>") runs every night as
        # part of Symphony's own housekeeping -- a stable, always-active
        # anchor point that doesn't depend on any specific dataset
        # snapshot, unlike a fixed total-line-count assertion would.
        index = scan_report_logs(LOGS_REPORT_DIR, since=datetime(2026, 1, 1))

        key = ("consolidate", "$<consolidate_daily_logs>")
        self.assertIn(key, index)
        self.assertGreaterEqual(index[key], datetime(2026, 8, 1))

    def test_since_actually_narrows_the_scanned_file_set(self):
        full_index = scan_report_logs(LOGS_REPORT_DIR)
        narrow_index = scan_report_logs(LOGS_REPORT_DIR, since=datetime(2026, 8, 1))

        self.assertGreater(len(full_index), len(narrow_index))
        self.assertTrue(all(ts >= datetime(2026, 8, 1) for ts in narrow_index.values()))


if __name__ == "__main__":
    unittest.main()
