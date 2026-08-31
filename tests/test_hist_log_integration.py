import re
import unittest
from pathlib import Path

from rptsched_lib.hist_log import _read_lines, filter_raw_lines

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGS_HIST_DIR = REPO_ROOT / "logs" / "Hist"


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


if __name__ == "__main__":
    unittest.main()
