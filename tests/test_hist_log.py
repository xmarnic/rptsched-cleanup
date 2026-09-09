import gzip
import subprocess
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rptsched_lib.hist_log import (
    _read_lines,
    decode,
    filter_raw_lines,
    find_hist_files,
    parse_decoded_records,
    scan_hist_logs,
)


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


class TestReadLines(unittest.TestCase):
    def test_z_file_with_invalid_utf8_byte_does_not_raise(self):
        # Real production .hist.Z files contain non-UTF-8 bytes (confirmed
        # against the first live production run: UnicodeDecodeError on byte
        # 0xc3 via zcat's default strict-utf8 decoding). Plain-text .hist
        # already used errors="replace"; the .Z branch needs the same.
        with TemporaryDirectory() as tmp:
            hist_path = Path(tmp) / "202608.hist.Z"
            with gzip.open(hist_path, "wb") as f:
                f.write(b"^S1ge\xc3invalid\n^S2gk valid\n")

            lines = _read_lines(hist_path)

            self.assertEqual(len(lines), 2)
            self.assertIn("^S2gk valid", lines)


class TestParseDecodedRecords(unittest.TestCase):
    # All synthetic fixtures below follow the exact real logprint |
    # translate format verified against a real production sample
    # (decoded-hist-log.txt, not committed -- contains real staff
    # usernames/emails), with fabricated ids/libraries/names.

    BOILERPLATE = (
        ".report\n"
        ".title\n"
        "Log Listing\n"
        "Produced Monday, August 31, 2026 at 4:26 PM\n"
        "\n\n"
        ".end\n"
        "\n"
    )

    def test_skips_report_boilerplate_header(self):
        self.assertEqual(parse_decoded_records(self.BOILERPLATE), [])

    def test_parses_create_scheduled_report_without_owner_field(self):
        text = (
            "8/31/2026,08:00:00 Station: 0086 Request: Sequence #: 08 Command: Create Scheduled Report\n"
            "station login user access:17TECH  station library:CAMP  station login clearance:NONE  "
            "station user's user ID:CAMPBIBMGR  station:PCGUI-DISP  schedule id:kdih  "
            "name of run script:illholdlist  scheduled report name:ILL holds - My patrons unfilled CAMP  "
            "frequency that the report will run:a  date and time of the last running:10/21/2025,18:25  "
            "printer to auto-print report to:  address to email report to:  should notices be emailed?:N  "
            "place onto printlist:Y  oL:Y  oI:  kc:Y  kd:Y  oR:N  Report Email Subject Line:Library notice  "
            "Report Email Subject Language:ENGLISH  ky:  Max length of transaction response:3000000  \n"
            "\n"
        )
        entries = parse_decoded_records(text)

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.command, "Create Scheduled Report")
        self.assertEqual(entry.timestamp, datetime(2026, 8, 31, 8, 0, 0))
        self.assertEqual(entry.schedule_id, "kdih")
        self.assertEqual(entry.report_source, "illholdlist")
        self.assertEqual(entry.description, "ILL holds - My patrons unfilled CAMP")
        self.assertEqual(entry.owner, "CAMPBIBMGR")  # falls back to acting user
        self.assertEqual(entry.frequency, "a")

    def test_parses_create_scheduled_report_with_explicit_owner_field(self):
        text = (
            "8/31/2026,10:53:03 Station: 0167 Request: Sequence #: 63 Command: Create Scheduled Report\n"
            "station login user access:WADMIN  station library:WYLD  station login clearance:NONE  "
            "station user's user ID:NMARLIN  station:PCGUI-DISP  schedule id:kdll  "
            "name of run script:usercnt  scheduled report name:Count Users Test  "
            "frequency that the report will run:a  date and time the report will run:08/31/2026,10:52  "
            "date and time of the last running:NEVER  login of the owner of the report:OTHERMGR  "
            "printer to auto-print report to:  address to email report to:  place onto printlist:Y  "
            "oL:Y  oI:  kc:Y  kd:Y  oR:N  Max length of transaction response:3000000  \n"
            "\n"
        )
        entries = parse_decoded_records(text)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].owner, "OTHERMGR")  # explicit field wins over acting user

    def test_parses_remove_finished_report(self):
        text = (
            "8/31/2026,08:07:15 Station: 0065 Request: Sequence #: 42 Command: Remove Finished Report\n"
            "station login user access:14TECH  station library:NIOB  station login clearance:NONE  "
            "station user's user ID:NIOBBIBMGR  station:PCGUI-DISP  schedule id:gzby  "
            "name of run script:statistics  scheduled report name:NIOB daily Statistics  "
            "login of the owner of the report:NIOBBIBMGR  Max length of transaction response:3000000  \n"
            "\n"
        )
        entries = parse_decoded_records(text)

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.command, "Remove Finished Report")
        self.assertEqual(entry.report_source, "statistics")
        self.assertEqual(entry.description, "NIOB daily Statistics")
        self.assertEqual(entry.owner, "NIOBBIBMGR")
        self.assertIsNone(entry.frequency)  # not carried on this command

    def test_handles_internal_double_space_in_description(self):
        text = (
            "8/31/2026,08:07:15 Station: 0065 Request: Sequence #: 43 Command: Remove Finished Report\n"
            "station login user access:14TECH  station library:NIOB  station login clearance:NONE  "
            "station user's user ID:NIOBBIBMGR  station:PCGUI-DISP  schedule id:gywy  "
            "name of run script:noverduepl2  scheduled report name:NIOB  FINAL  "
            "login of the owner of the report:NIOBBIBMGR  Max length of transaction response:3000000  \n"
            "\n"
        )
        entries = parse_decoded_records(text)

        self.assertEqual(entries[0].description, "NIOB  FINAL")

    def test_skips_remove_scheduled_report_no_usage_fields(self):
        text = (
            "8/31/2026,13:15:12 Station: 0167 Request: Sequence #: 73 Command: Remove Scheduled Report\n"
            "station login user access:WADMIN  station library:WYLD  station login clearance:NONE  "
            "station user's user ID:NMARLIN  station:PCGUI-DISP  schedule id:kdkx  "
            "Max length of transaction response:3000000  \n"
            "\n"
        )
        self.assertEqual(parse_decoded_records(text), [])

    def test_skips_modify_scheduled_report(self):
        text = (
            "8/31/2026,10:23:48 Station: 0304 Request: Sequence #: 07 Command: Modify Scheduled Report\n"
            "station login user access:2401ACQ  station library:WSL  station login clearance:NONE  "
            "station user's user ID:WSLACQMGR  station:PCGUI-DISP  schedule id:efgl  "
            "date and time the report will run:09/10/2026,18:00  oL:Y  kc:Y  kd:Y  oR:N  "
            "Max length of transaction response:5000000  \n"
            "\n"
        )
        self.assertEqual(parse_decoded_records(text), [])

    def test_skips_rename_scheduled_report_even_when_wrapped_across_lines(self):
        text = (
            "8/31/2026,14:18:07 Station: 0107 Request: Sequence #: 97 Command: Rename Scheduled Report\n"
            "station login user access:17CIRC  station library:CAMP  station login clearance:NONE  "
            "station user's user ID:CAMPCIRCMGR  station:PCGUI-DISP  schedule id:kdpv  oS:xoll  "
            "name of run script:assumedlost  scheduled report name:CAMP - ASSUMED LOST NOTICES  "
            "frequency that the report will run:w  Report Email Subject Line:Library Notice  \n"
            "Report Email Subject Language:ENGLISH  ky:  Max length of transaction response:900000  \n"
            "\n"
        )
        self.assertEqual(parse_decoded_records(text), [])

    def test_multiline_wrap_on_a_usage_command_still_parses_correctly(self):
        # Verified in real data: wraps always happen at a field boundary,
        # never mid-value.
        text = (
            "8/31/2026,14:44:34 Station: 0107 Request: Sequence #: 92 Command: Create Scheduled Report\n"
            "station login user access:17CIRC  station library:CAMP  station login clearance:NONE  "
            "station user's user ID:CAMPCIRCMGR  station:PCGUI-DISP  schedule id:kdqn  "
            "name of run script:chargeitem  scheduled report name:Long Report Name Here  "
            "frequency that the report will run:a  Report Email Subject Line:Library notice  \n"
            "Report Email Subject Language:ENGLISH  ky:  Max length of transaction response:900000  \n"
            "\n"
        )
        entries = parse_decoded_records(text)

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].report_source, "chargeitem")
        self.assertEqual(entries[0].description, "Long Report Name Here")


class TestScanHistLogs(unittest.TestCase):
    def test_builds_index_from_matching_command_types(self):
        create_text = (
            "8/31/2026,08:00:00 Station: 0086 Request: Sequence #: 08 Command: Create Scheduled Report\n"
            "station login user access:17TECH  station library:CAMP  station login clearance:NONE  "
            "station user's user ID:CAMPBIBMGR  station:PCGUI-DISP  schedule id:kdih  "
            "name of run script:illholdlist  scheduled report name:My Report  "
            "frequency that the report will run:a  Max length of transaction response:3000000  \n"
            "\n"
        )
        with TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            (logs_dir / "202608.hist").write_text("irrelevant raw content ^S08ge...\n")

            with patch("rptsched_lib.hist_log._read_lines", return_value=["^S08ge..."]), patch(
                "rptsched_lib.hist_log.decode", return_value=create_text
            ):
                index = scan_hist_logs(logs_dir)

        self.assertEqual(
            index,
            {("illholdlist", "My Report", "CAMPBIBMGR"): datetime(2026, 8, 31, 8, 0, 0)},
        )


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
