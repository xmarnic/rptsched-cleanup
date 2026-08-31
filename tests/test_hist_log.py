import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rptsched_lib.hist_log import decode, filter_raw_lines, find_hist_files
from datetime import datetime


class TestFilterRawLines(unittest.TestCase):
    def test_keeps_create_scheduled_report_line(self):
        line = "E202608310800000086R ^S08geFF17TECH^FECAMP^FcNONE^FWCAMPBIBMGR^FDPCGUI-DISP^oakdih^obillholdlist"
        self.assertEqual(filter_raw_lines([line]), [line])

    def test_keeps_all_five_confirmed_codes(self):
        lines = [
            "^S1ge...",
            "^S2gg...",
            "^S3gh...",
            "^S4gk...",
            "^S5gu...",
        ]
        self.assertEqual(filter_raw_lines(lines), lines)

    def test_drops_set_report_options_noise(self):
        line = "^S93goFF17TECH^FECAMP^FcNONE^FWCAMPBIBMGR^FDPCGUI-DISP^oaftfw^obillholdlist"
        self.assertEqual(filter_raw_lines([line]), [])

    def test_drops_unrelated_circulation_line(self):
        line = "E202608310001240063R ^S07IYFWSIPCHK57^FETETN^FFSIPCHK^FcNONE^FDSIPCHK^dC6"
        self.assertEqual(filter_raw_lines([line]), [])

    def test_empty_input_returns_empty(self):
        self.assertEqual(filter_raw_lines([]), [])


class TestFindHistFiles(unittest.TestCase):
    def test_finds_monthly_and_daily_hist_files(self):
        with TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            (logs_dir / "202608.hist").write_text("")
            (logs_dir / "20260831.hist").write_text("")
            (logs_dir / "202607.hist.Z").write_bytes(b"")
            (logs_dir / "notahist.txt").write_text("")

            files = find_hist_files(logs_dir)

            self.assertEqual(
                {f.name for f in files},
                {"202608.hist", "20260831.hist", "202607.hist.Z"},
            )

    def test_since_filters_out_older_months_by_filename(self):
        with TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            (logs_dir / "201406.hist.Z").write_bytes(b"")
            (logs_dir / "202608.hist").write_text("")

            files = find_hist_files(logs_dir, since=datetime(2026, 1, 1))

            self.assertEqual({f.name for f in files}, {"202608.hist"})


class TestDecode(unittest.TestCase):
    def test_empty_input_skips_subprocess_entirely(self):
        with patch("rptsched_lib.hist_log.subprocess.run") as mock_run:
            result = decode([])

        mock_run.assert_not_called()
        self.assertEqual(result, "")

    def test_pipes_raw_lines_through_logprint_then_translate(self):
        raw_lines = ["^S08ge...", "^S09gk..."]
        with patch("rptsched_lib.hist_log.subprocess.run") as mock_run:
            mock_run.side_effect = [
                type("R", (), {"stdout": "LOGPRINT DECODED OUTPUT\n"})(),
                type("R", (), {"stdout": "TRANSLATED OUTPUT\n"})(),
            ]
            result = decode(raw_lines)

        self.assertEqual(result, "TRANSLATED OUTPUT\n")
        self.assertEqual(mock_run.call_count, 2)

        logprint_call = mock_run.call_args_list[0]
        self.assertEqual(logprint_call.args[0], ["logprint"])
        self.assertEqual(logprint_call.kwargs["input"], "^S08ge...\n^S09gk...\n")

        translate_call = mock_run.call_args_list[1]
        self.assertEqual(translate_call.args[0], ["translate"])
        self.assertEqual(translate_call.kwargs["input"], "LOGPRINT DECODED OUTPUT\n")


if __name__ == "__main__":
    unittest.main()
