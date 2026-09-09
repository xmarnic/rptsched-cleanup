import subprocess
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rptsched_lib.report_log import find_log_files, parse_line, scan_report_logs


class TestParseLine(unittest.TestCase):
    def test_parses_finished_report_line(self):
        line = '20230101001007 Finished report setreports:"Set simultaneous reports number 1"'
        self.assertEqual(
            parse_line(line),
            ("setreports", "Set simultaneous reports number 1", datetime(2023, 1, 1, 0, 10, 7)),
        )

    def test_ignores_starting_report_line(self):
        line = '20230101001003 Starting report consolidate:"$<consolidate_daily_logs>"'
        self.assertIsNone(parse_line(line))

    def test_ignores_adding_to_finished_list_line(self):
        line = "20230101001007 Adding report setreports:Set simultaneous reports number 1 to finished list"
        self.assertIsNone(parse_line(line))

    def test_ignores_mailing_line(self):
        line = '20230101040738 Automatically mailing report adutext:"Add, Delete, Update Databases" to a@b.com'
        self.assertIsNone(parse_line(line))

    def test_ignores_missing_parameter_file_line(self):
        line = '20230101000003 Missing parameter file for CONV-GLEN List Funds:"azbh"'
        self.assertIsNone(parse_line(line))

    def test_ignores_blank_line(self):
        self.assertIsNone(parse_line(""))


class TestFindLogFiles(unittest.TestCase):
    def test_finds_monthly_and_daily_log_files(self):
        with TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            (logs_dir / "202608.log").write_text("")
            (logs_dir / "20260831.log").write_text("")
            (logs_dir / "202607.log.Z").write_bytes(b"")
            (logs_dir / "notalog.txt").write_text("")

            files = find_log_files(logs_dir)

            self.assertEqual(
                {f.name for f in files},
                {"202608.log", "20260831.log", "202607.log.Z"},
            )

    def test_since_filters_out_older_months_by_filename(self):
        with TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            (logs_dir / "202101.log.Z").write_bytes(b"")
            (logs_dir / "202608.log").write_text("")

            files = find_log_files(logs_dir, since=datetime(2026, 1, 1))

            self.assertEqual({f.name for f in files}, {"202608.log"})


class TestScanReportLogs(unittest.TestCase):
    def test_builds_index_keyed_by_report_source_and_description(self):
        with TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            (logs_dir / "202608.log").write_text(
                '20260801120000 Finished report noverdue:"My Report"\n'
                '20260815120000 Finished report noverdue:"My Report"\n'
                '20260805120000 Finished report otherreport:"Other"\n'
            )

            index = scan_report_logs(logs_dir)

            self.assertEqual(
                index,
                {
                    ("noverdue", "My Report"): datetime(2026, 8, 15, 12, 0, 0),
                    ("otherreport", "Other"): datetime(2026, 8, 5, 12, 0, 0),
                },
            )

    def test_since_excludes_older_entries_within_a_kept_file(self):
        with TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            (logs_dir / "202608.log").write_text(
                '20260801120000 Finished report noverdue:"My Report"\n'
            )

            index = scan_report_logs(logs_dir, since=datetime(2026, 8, 10))

            self.assertEqual(index, {})

    def test_reads_compressed_log_via_zcat(self):
        with TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            z_path = logs_dir / "202301.log.Z"
            z_path.write_bytes(b"\x1f\x9d")  # placeholder; zcat call itself is mocked below

            fake_zcat_output = '20230101001007 Finished report setreports:"Set simultaneous reports number 1"\n'
            with patch("rptsched_lib.report_log.subprocess.run") as mock_run:
                mock_run.return_value.stdout = fake_zcat_output
                index = scan_report_logs(logs_dir)

            mock_run.assert_called_once_with(
                ["zcat", str(z_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                check=True,
            )
            self.assertEqual(
                index,
                {("setreports", "Set simultaneous reports number 1"): datetime(2023, 1, 1, 0, 10, 7)},
            )


if __name__ == "__main__":
    unittest.main()
