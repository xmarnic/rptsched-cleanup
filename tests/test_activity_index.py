import json
import os
import time
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rptsched_lib import report_log
from rptsched_lib.activity_index import ActivityIndex, build_activity_index, is_active


class TestIsActive(unittest.TestCase):
    def test_true_when_report_index_has_key_regardless_of_owner(self):
        index = ActivityIndex(
            report_index={("noverdue", "My Report"): datetime(2026, 1, 1)},
            hist_index={},
        )
        self.assertTrue(is_active(index, "noverdue", "My Report", owner="ANYONE"))

    def test_true_when_hist_index_has_exact_triple(self):
        index = ActivityIndex(
            report_index={},
            hist_index={("illholdlist", "My Report", "CAMPBIBMGR"): datetime(2026, 1, 1)},
        )
        self.assertTrue(is_active(index, "illholdlist", "My Report", owner="CAMPBIBMGR"))

    def test_false_when_hist_index_owner_does_not_match(self):
        index = ActivityIndex(
            report_index={},
            hist_index={("illholdlist", "My Report", "CAMPBIBMGR"): datetime(2026, 1, 1)},
        )
        self.assertFalse(is_active(index, "illholdlist", "My Report", owner="OTHERMGR"))

    def test_false_when_neither_index_has_the_key(self):
        index = ActivityIndex(report_index={}, hist_index={})
        self.assertFalse(is_active(index, "noverdue", "My Report", owner="SOMEMGR"))


class TestBuildActivityIndexWithoutCache(unittest.TestCase):
    def test_merges_both_sources_via_top_level_scan_functions(self):
        with TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "Report"
            hist_dir = Path(tmp) / "Hist"
            report_dir.mkdir()
            hist_dir.mkdir()
            (report_dir / "202608.log").write_text(
                '20260805120000 Finished report noverdue:"My Report"\n'
            )
            (hist_dir / "202608.hist").write_text("irrelevant raw ^S01ge...\n")

            hist_entries_text = (
                "8/31/2026,08:00:00 Station: 0086 Request: Sequence #: 08 Command: Create Scheduled Report\n"
                "station login user access:17TECH  station library:CAMP  station login clearance:NONE  "
                "station user's user ID:CAMPBIBMGR  station:PCGUI-DISP  schedule id:kdih  "
                "name of run script:illholdlist  scheduled report name:Other Report  "
                "frequency that the report will run:a  Max length of transaction response:3000000  \n"
                "\n"
            )
            with patch("rptsched_lib.hist_log.decode", return_value=hist_entries_text):
                index = build_activity_index(report_dir, hist_dir, since=datetime(2026, 1, 1))

            self.assertEqual(
                index.report_index,
                {("noverdue", "My Report"): datetime(2026, 8, 5, 12, 0, 0)},
            )
            self.assertEqual(
                index.hist_index,
                {("illholdlist", "Other Report", "CAMPBIBMGR"): datetime(2026, 8, 31, 8, 0, 0)},
            )


class TestBuildActivityIndexWithCache(unittest.TestCase):
    def test_second_build_reuses_cached_report_entries_when_file_unchanged(self):
        with TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "Report"
            hist_dir = Path(tmp) / "Hist"
            report_dir.mkdir()
            hist_dir.mkdir()
            (report_dir / "202608.log").write_text(
                '20260805120000 Finished report noverdue:"My Report"\n'
            )
            cache_path = Path(tmp) / "cache.json"

            with patch(
                "rptsched_lib.activity_index.report_log.iter_log_entries",
                wraps=report_log.iter_log_entries,
            ) as spy:
                build_activity_index(report_dir, hist_dir, since=datetime(2026, 1, 1), cache_path=cache_path)
                self.assertEqual(spy.call_count, 1)

                build_activity_index(report_dir, hist_dir, since=datetime(2026, 1, 1), cache_path=cache_path)
                self.assertEqual(spy.call_count, 1)  # unchanged mtime -> cache hit, no second read

    def test_cache_invalidates_when_file_mtime_changes(self):
        with TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "Report"
            hist_dir = Path(tmp) / "Hist"
            report_dir.mkdir()
            hist_dir.mkdir()
            log_path = report_dir / "202608.log"
            log_path.write_text('20260805120000 Finished report noverdue:"My Report"\n')
            cache_path = Path(tmp) / "cache.json"

            build_activity_index(report_dir, hist_dir, since=datetime(2026, 1, 1), cache_path=cache_path)

            # append a new entry and bump mtime forward
            with log_path.open("a") as f:
                f.write('20260810120000 Finished report noverdue:"My Report"\n')
            future = time.time() + 5
            os.utime(log_path, (future, future))

            index = build_activity_index(report_dir, hist_dir, since=datetime(2026, 1, 1), cache_path=cache_path)

            self.assertEqual(
                index.report_index,
                {("noverdue", "My Report"): datetime(2026, 8, 10, 12, 0, 0)},
            )

    def test_hist_decode_not_called_again_when_file_unchanged(self):
        with TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "Report"
            hist_dir = Path(tmp) / "Hist"
            report_dir.mkdir()
            hist_dir.mkdir()
            (hist_dir / "202608.hist").write_text("irrelevant raw ^S01ge...\n")
            cache_path = Path(tmp) / "cache.json"

            with patch("rptsched_lib.hist_log.decode", return_value="") as mock_decode:
                build_activity_index(report_dir, hist_dir, since=datetime(2026, 1, 1), cache_path=cache_path)
                self.assertEqual(mock_decode.call_count, 1)

                build_activity_index(report_dir, hist_dir, since=datetime(2026, 1, 1), cache_path=cache_path)
                self.assertEqual(mock_decode.call_count, 1)  # cache hit, decode not called again

    def test_corrupt_cache_file_falls_back_to_full_rescan_instead_of_crashing(self):
        with TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "Report"
            hist_dir = Path(tmp) / "Hist"
            report_dir.mkdir()
            hist_dir.mkdir()
            (report_dir / "202608.log").write_text(
                '20260805120000 Finished report noverdue:"My Report"\n'
            )
            cache_path = Path(tmp) / "cache.json"
            cache_path.write_text("not valid json{{{")

            index = build_activity_index(report_dir, hist_dir, since=datetime(2026, 1, 1), cache_path=cache_path)

            self.assertEqual(
                index.report_index,
                {("noverdue", "My Report"): datetime(2026, 8, 5, 12, 0, 0)},
            )

    def test_cache_file_is_valid_json_after_a_build(self):
        with TemporaryDirectory() as tmp:
            report_dir = Path(tmp) / "Report"
            hist_dir = Path(tmp) / "Hist"
            report_dir.mkdir()
            hist_dir.mkdir()
            (report_dir / "202608.log").write_text(
                '20260805120000 Finished report noverdue:"My Report"\n'
            )
            cache_path = Path(tmp) / "cache.json"

            build_activity_index(report_dir, hist_dir, since=datetime(2026, 1, 1), cache_path=cache_path)

            with cache_path.open() as f:
                cache = json.load(f)
            self.assertIn("202608.log", cache["report_log"])


if __name__ == "__main__":
    unittest.main()
