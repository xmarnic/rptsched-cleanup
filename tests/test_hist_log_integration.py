import re
import unittest
from datetime import datetime
from pathlib import Path

from rptsched_lib.hist_log import _read_lines, filter_raw_lines, parse_decoded_records

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGS_HIST_DIR = REPO_ROOT / "logs" / "Hist"
# Real logprint | translate output for 20260831.hist's ^S[0-9]+g[ehgku]
# subset, produced on the production server (this dev machine has no
# logprint/translate). Gitignored -- contains real staff usernames and
# emails, not committed. This is what actually lets the decoded-text
# parser be verified against real production output, not just synthetic
# fixtures built from a read of that same file.
DECODED_HIST_SAMPLE = REPO_ROOT / "decoded-hist-log.txt"


@unittest.skipUnless(LOGS_HIST_DIR.is_dir(), "local logs/Hist/ pull not present")
class TestFilterRawLinesAgainstRealData(unittest.TestCase):
    def test_matches_known_command_code_tally_for_one_day(self):
        # Cross-checked by hand against a decoded command-vocabulary
        # survey of the same file earlier in this investigation:
        # ge=72, gg=5, gh=9, gk=62, gu=11 -> 159 total. See
        # 2026-08-31-report-log-data-sources-and-tagging-roadmap.md.
        day_file = LOGS_HIST_DIR / "20260831.hist"
        if not day_file.is_file():
            self.skipTest("20260831.hist not present in local pull")

        lines = _read_lines(day_file)
        matched = filter_raw_lines(lines)

        self.assertEqual(len(matched), 159)

    def test_does_not_pick_up_go_noise_or_unrelated_transactions(self):
        day_file = LOGS_HIST_DIR / "20260831.hist"
        if not day_file.is_file():
            self.skipTest("20260831.hist not present in local pull")

        lines = _read_lines(day_file)
        matched = filter_raw_lines(lines)

        self.assertTrue(all("^S" in line for line in matched))
        # go (Set Report Options) is excluded by design -- confirm no
        # matched line's code position is actually "go".
        code_pattern = re.compile(r"\^S\d+(\w{2})")
        codes = {code_pattern.search(line).group(1) for line in matched}
        self.assertEqual(codes, {"ge", "gg", "gh", "gk", "gu"})


@unittest.skipUnless(DECODED_HIST_SAMPLE.is_file(), "local decoded-hist-log.txt sample not present")
class TestParseDecodedRecordsAgainstRealDecodedSample(unittest.TestCase):
    def test_parses_expected_total_and_command_split(self):
        text = DECODED_HIST_SAMPLE.read_text()

        entries = parse_decoded_records(text)

        self.assertEqual(len(entries), 140)
        by_command = {}
        for entry in entries:
            by_command[entry.command] = by_command.get(entry.command, 0) + 1
        self.assertEqual(by_command, {"Create Scheduled Report": 77, "Remove Finished Report": 63})

    def test_no_missing_fields_across_any_real_entry(self):
        # Confirms the owner fallback (station user's user ID when "login
        # of the owner of the report" is absent) actually closes the gap
        # on every real record, not just the synthetic cases covered in
        # test_hist_log.py.
        text = DECODED_HIST_SAMPLE.read_text()

        entries = parse_decoded_records(text)

        self.assertTrue(all(e.report_source is not None for e in entries))
        self.assertTrue(all(e.description is not None for e in entries))
        self.assertTrue(all(e.owner is not None for e in entries))

    def test_matches_a_specific_known_real_record(self):
        text = DECODED_HIST_SAMPLE.read_text()

        entries = parse_decoded_records(text)

        matches = [e for e in entries if e.schedule_id == "gzby"]
        self.assertEqual(len(matches), 1)
        entry = matches[0]
        self.assertEqual(entry.command, "Remove Finished Report")
        self.assertEqual(entry.report_source, "statistics")
        self.assertEqual(entry.description, "NIOB daily Statistics")
        self.assertEqual(entry.owner, "NIOBBIBMGR")
        self.assertEqual(entry.timestamp, datetime(2026, 8, 31, 8, 7, 15))

    def test_internal_double_space_description_survives_real_data_too(self):
        text = DECODED_HIST_SAMPLE.read_text()

        entries = parse_decoded_records(text)

        matches = [e for e in entries if e.schedule_id == "gywy"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].description, "NIOB  FINAL")


if __name__ == "__main__":
    unittest.main()
