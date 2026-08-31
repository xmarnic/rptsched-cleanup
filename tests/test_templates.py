import unittest
from datetime import datetime
from tempfile import TemporaryDirectory

from rptsched_lib.activity_index import ActivityIndex
from rptsched_lib.templates import count_manual_templates, find_stale_template_candidates
from tests.fixtures import make_data_dir

TODAY = datetime(2026, 7, 24)
EMPTY_INDEX = ActivityIndex(report_index={}, hist_index={})


def _line(template_id, frequency_flag="n", created="200207021051", last_run="200507270844", owner="SOMEMGR", description="Some Template", report_type="noverdue"):
    return "{}|{}|{}|{}|{}|{}|{}||||||0|3||0|$<library_notice:c>|ENGLISH|".format(
        template_id, report_type, description, frequency_flag, created, last_run, owner
    )


class TestFindStaleTemplateCandidates(unittest.TestCase):
    def test_selects_manual_template_with_no_activity_and_old_created(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", created="200207021051")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set", "abcd.selans"])

            candidates = find_stale_template_candidates(data_dir, EMPTY_INDEX, years=3, today=TODAY)

            self.assertEqual(set(candidates.keys()), {"abcd"})
            candidate = candidates["abcd"]
            self.assertEqual(candidate.filenames, ["abcd.selans", "abcd.set"])
            self.assertEqual(candidate.frequency_flag, "n")
            self.assertEqual(candidate.report_type, "noverdue")

    def test_no_activity_but_recently_created_is_protected_by_recency_floor(self):
        with TemporaryDirectory() as tmp:
            # created a month before TODAY -> well within the 3yr window,
            # protected even though no log activity was ever found
            lines = [_line("abcd", created="202606240000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(data_dir, EMPTY_INDEX, years=3, today=TODAY)

            self.assertEqual(candidates, {})

    def test_excludes_recurring_frequency_flag(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", frequency_flag="w1")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(data_dir, EMPTY_INDEX, years=3, today=TODAY)

            self.assertEqual(candidates, {})

    def test_no_owner_exclusions_by_default(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", owner="ACQ")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(data_dir, EMPTY_INDEX, years=3, today=TODAY)

            self.assertEqual(set(candidates.keys()), {"abcd"})

    def test_exclude_owners_is_exact_match_case_insensitive(self):
        with TemporaryDirectory() as tmp:
            lines = [
                _line("abcd", owner="acqMGR"),
                _line("efgh", owner="ACQMGR"),
            ]
            data_dir = make_data_dir(tmp, lines, ["abcd.set", "efgh.set"])

            candidates = find_stale_template_candidates(
                data_dir, EMPTY_INDEX, years=3, today=TODAY, exclude_owners=["acqmgr"],
            )

            self.assertEqual(candidates, {})

    def test_exclude_owners_does_not_match_as_substring(self):
        with TemporaryDirectory() as tmp:
            # exclude_owners=["ACQ1"] should not catch an owner that merely contains "ACQ1"
            lines = [_line("abcd", owner="ACQ10")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(
                data_dir, EMPTY_INDEX, years=3, today=TODAY, exclude_owners=["ACQ1"],
            )

            self.assertEqual(set(candidates.keys()), {"abcd"})

    def test_exclude_owner_regexes_matches_as_unanchored_substring(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", owner="ACQHQ")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(
                data_dir, EMPTY_INDEX, years=3, today=TODAY, exclude_owner_regexes=["acq"],
            )

            self.assertEqual(candidates, {})

    def test_exclude_owner_regexes_respects_anchors(self):
        with TemporaryDirectory() as tmp:
            lines = [
                _line("abcd", owner="ACQ1"),
                _line("efgh", owner="jsmith-acq"),
            ]
            data_dir = make_data_dir(tmp, lines, ["abcd.set", "efgh.set"])

            candidates = find_stale_template_candidates(
                data_dir, EMPTY_INDEX, years=3, today=TODAY, exclude_owner_regexes=["^acq"],
            )

            self.assertEqual(set(candidates.keys()), {"efgh"})

    def test_report_index_match_excludes_regardless_of_owner(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", report_type="noverdue", description="Some Template", owner="SOMEMGR")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])
            index = ActivityIndex(
                report_index={("noverdue", "Some Template"): datetime(2026, 6, 1)},
                hist_index={},
            )

            candidates = find_stale_template_candidates(data_dir, index, years=3, today=TODAY)

            self.assertEqual(candidates, {})

    def test_hist_index_match_requires_owner_to_match(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", report_type="noverdue", description="Some Template", owner="SOMEMGR")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])
            # hist activity recorded under a different owner -> shouldn't protect this row
            index = ActivityIndex(
                report_index={},
                hist_index={("noverdue", "Some Template", "OTHERMGR"): datetime(2026, 6, 1)},
            )

            candidates = find_stale_template_candidates(data_dir, index, years=3, today=TODAY)

            self.assertEqual(set(candidates.keys()), {"abcd"})

    def test_hist_index_match_with_correct_owner_excludes(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", report_type="noverdue", description="Some Template", owner="SOMEMGR")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])
            index = ActivityIndex(
                report_index={},
                hist_index={("noverdue", "Some Template", "SOMEMGR"): datetime(2026, 6, 1)},
            )

            candidates = find_stale_template_candidates(data_dir, index, years=3, today=TODAY)

            self.assertEqual(candidates, {})

    def test_custom_years_threshold_changes_recency_floor(self):
        with TemporaryDirectory() as tmp:
            # is_active() trusts that the index it's given was already
            # windowed to the requested --years by build_activity_index's
            # own since= (that's the whole point of building it once) --
            # so the years-sensitive behavior left to test here is the
            # recency floor: created ~1.5yr before TODAY is protected at
            # years=3, a candidate at years=1, with no activity index
            # involved either way.
            lines = [_line("abcd", created="202501010000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            self.assertEqual(find_stale_template_candidates(data_dir, EMPTY_INDEX, years=3, today=TODAY), {})
            self.assertEqual(
                set(find_stale_template_candidates(data_dir, EMPTY_INDEX, years=1, today=TODAY).keys()),
                {"abcd"},
            )

    def test_candidate_with_no_files_on_disk_has_empty_filenames(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd")]
            data_dir = make_data_dir(tmp, lines, [])

            candidates = find_stale_template_candidates(data_dir, EMPTY_INDEX, years=3, today=TODAY)

            self.assertEqual(candidates["abcd"].filenames, [])

    def test_defaults_today_to_now(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", created="200207021051")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(data_dir, EMPTY_INDEX)  # no today= override

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
            lines = [
                _line("aaaa", owner="ACQ"),
                _line("bbbb", owner="SOMEMGR"),
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
