import unittest
from datetime import datetime
from tempfile import TemporaryDirectory

from rptsched_lib.templates import count_manual_templates, find_stale_template_candidates
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

    def test_no_owner_exclusions_by_default(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", owner="ACQ", last_run="202001010000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(data_dir, years=3, today=TODAY)

            self.assertEqual(set(candidates.keys()), {"abcd"})

    def test_exclude_owners_is_exact_match_case_insensitive(self):
        with TemporaryDirectory() as tmp:
            lines = [
                _line("abcd", owner="acqMGR", last_run="202001010000"),
                _line("efgh", owner="ACQMGR", last_run="202001010000"),
            ]
            data_dir = make_data_dir(tmp, lines, ["abcd.set", "efgh.set"])

            candidates = find_stale_template_candidates(
                data_dir, years=3, today=TODAY, exclude_owners=["acqmgr"],
            )

            self.assertEqual(candidates, {})

    def test_exclude_owners_does_not_match_as_substring(self):
        with TemporaryDirectory() as tmp:
            # exclude_owners=["ACQ1"] should not catch an owner that merely contains "ACQ1"
            lines = [_line("abcd", owner="ACQ10", last_run="202001010000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(
                data_dir, years=3, today=TODAY, exclude_owners=["ACQ1"],
            )

            self.assertEqual(set(candidates.keys()), {"abcd"})

    def test_exclude_owner_regexes_matches_as_unanchored_substring(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", owner="ACQHQ", last_run="202001010000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(
                data_dir, years=3, today=TODAY, exclude_owner_regexes=["acq"],
            )

            self.assertEqual(candidates, {})

    def test_exclude_owner_regexes_respects_anchors(self):
        with TemporaryDirectory() as tmp:
            lines = [
                _line("abcd", owner="ACQ1", last_run="202001010000"),
                _line("efgh", owner="jsmith-acq", last_run="202001010000"),
            ]
            data_dir = make_data_dir(tmp, lines, ["abcd.set", "efgh.set"])

            candidates = find_stale_template_candidates(
                data_dir, years=3, today=TODAY, exclude_owner_regexes=["^acq"],
            )

            self.assertEqual(set(candidates.keys()), {"efgh"})

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


class TestCountManualTemplates(unittest.TestCase):
    def test_counts_only_manual_frequency_flag(self):
        with TemporaryDirectory() as tmp:
            lines = [
                _line("aaaa", frequency_flag="n"),
                _line("bbbb", frequency_flag="w1"),
                _line("cccc", frequency_flag="n"),
            ]
            data_dir = make_data_dir(tmp, lines, [])

            self.assertEqual(count_manual_templates(data_dir), 2)

    def test_ignores_staleness_and_owner(self):
        with TemporaryDirectory() as tmp:
            # active (not stale) and ACQ-owned, but still manual -> both counted
            lines = [
                _line("aaaa", owner="ACQ", last_run="202601010000"),
                _line("bbbb", owner="SOMEMGR", last_run="202001010000"),
            ]
            data_dir = make_data_dir(tmp, lines, [])

            self.assertEqual(count_manual_templates(data_dir), 2)

    def test_zero_when_no_manual_templates(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("aaaa", frequency_flag="w1")]
            data_dir = make_data_dir(tmp, lines, [])

            self.assertEqual(count_manual_templates(data_dir), 0)


if __name__ == "__main__":
    unittest.main()
