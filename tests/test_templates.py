import unittest
from datetime import datetime
from tempfile import TemporaryDirectory

from rptsched_cleanup.templates import find_stale_template_candidates
from tests.fixtures import make_data_dir

TODAY = datetime(2026, 7, 24)


def _line(template_id, frequency_flag="n", created="200207021051", last_run="200507270844", owner="SOMEMGR", description="Some Template"):
    return "{}|noverdue|{}|{}|{}|{}|{}||||||0|3||0|$<library_notice:c>|ENGLISH|".format(
        template_id, description, frequency_flag, created, last_run, owner
    )


class TestFindStaleTemplateCandidates(unittest.TestCase):
    def test_selects_manual_template_inactive_by_last_run(self):
        with TemporaryDirectory() as tmp:
            # last_run 2020 -> 6+ years before 2026-07-24, well past the 3yr default
            lines = [_line("abcd", last_run="202001010000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set", "abcd.selans"])

            candidates = find_stale_template_candidates(data_dir, years=3, today=TODAY)

            self.assertEqual(set(candidates.keys()), {"abcd"})
            candidate = candidates["abcd"]
            self.assertEqual(candidate.filenames, ["abcd.selans", "abcd.set"])
            self.assertEqual(candidate.frequency_flag, "n")

    def test_falls_back_to_created_when_never_run(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", created="202001010000", last_run="0000000000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(data_dir, years=3, today=TODAY)

            self.assertEqual(set(candidates.keys()), {"abcd"})

    def test_excludes_recurring_frequency_flag(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", frequency_flag="w1", last_run="202001010000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(data_dir, years=3, today=TODAY)

            self.assertEqual(candidates, {})

    def test_excludes_acq_owner_case_insensitive(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", owner="acqMGR", last_run="202001010000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(data_dir, years=3, today=TODAY)

            self.assertEqual(candidates, {})

    def test_excludes_recently_active_template(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", last_run="202601010000")]  # Jan 2026, well within 3yr of 2026-07-24
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(data_dir, years=3, today=TODAY)

            self.assertEqual(candidates, {})

    def test_custom_years_threshold(self):
        with TemporaryDirectory() as tmp:
            # last_run Jan 2025 -> ~1.5 years before 2026-07-24: stale at years=1, not at years=3
            lines = [_line("abcd", last_run="202501010000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            self.assertEqual(find_stale_template_candidates(data_dir, years=3, today=TODAY), {})
            self.assertEqual(
                set(find_stale_template_candidates(data_dir, years=1, today=TODAY).keys()),
                {"abcd"},
            )

    def test_candidate_with_no_files_on_disk_has_empty_filenames(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", last_run="202001010000")]
            data_dir = make_data_dir(tmp, lines, [])

            candidates = find_stale_template_candidates(data_dir, years=3, today=TODAY)

            self.assertEqual(candidates["abcd"].filenames, [])

    def test_defaults_today_to_now(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", last_run="202001010000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(data_dir)  # no today= override

            self.assertEqual(set(candidates.keys()), {"abcd"})


if __name__ == "__main__":
    unittest.main()
