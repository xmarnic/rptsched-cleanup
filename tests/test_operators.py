import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rptsched_cleanup.operators import find_operator_mismatches, OperatorMismatch, SkippedId
from tests.fixtures import make_data_dir


def _schedlist_line(template_id, owner):
    return "{}|noverdue|Some Template|n|200207021051|202001010000|{}||||||0|3||0|$<library_notice:c>|ENGLISH|".format(
        template_id, owner
    )


def _write_set_file(data_dir, template_id, operator_value, middle_field=""):
    (data_dir / "{}.set".format(template_id)).write_text(
        "# Copyright (c) 1992 - 2000, Sirsi Corporation.\n"
        "desc|0||$(14837)|\n"
        "operator|0|{}|{}|\n"
        "title|0||-t$(14836)|\n".format(middle_field, operator_value)
    )


class TestFindOperatorMismatches(unittest.TestCase):
    def test_detects_mismatch(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "REALOWNER")], [])
            _write_set_file(data_dir, "abcd", "STALEOWNER")

            mismatches, skipped = find_operator_mismatches(data_dir)

            self.assertEqual(skipped, [])
            self.assertEqual(
                mismatches,
                {"abcd": OperatorMismatch(id="abcd", old_operator="STALEOWNER", new_operator="REALOWNER")},
            )

    def test_no_mismatch_when_operator_matches_owner(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "SAMEOWNER")], [])
            _write_set_file(data_dir, "abcd", "SAMEOWNER")

            mismatches, skipped = find_operator_mismatches(data_dir)

            self.assertEqual(mismatches, {})
            self.assertEqual(skipped, [])

    def test_comparison_is_case_sensitive(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "WRIGCIRCMGR")], [])
            _write_set_file(data_dir, "abcd", "wrigcircmgr")

            mismatches, skipped = find_operator_mismatches(data_dir)

            self.assertEqual(
                mismatches,
                {"abcd": OperatorMismatch(id="abcd", old_operator="wrigcircmgr", new_operator="WRIGCIRCMGR")},
            )

    def test_middle_field_is_not_compared_or_touched_by_detection(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("jiqi", "SIRSI")], [])
            _write_set_file(data_dir, "jiqi", "SIRSI", middle_field="SIRSI")

            mismatches, skipped = find_operator_mismatches(data_dir)

            self.assertEqual(mismatches, {})

    def test_skips_id_with_no_matching_set_file(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "REALOWNER")], [])
            # no abcd.set written at all

            mismatches, skipped = find_operator_mismatches(data_dir)

            self.assertEqual(mismatches, {})
            self.assertEqual(skipped, [SkippedId(id="abcd", reason="missing .set file")])

    def test_skips_id_with_no_operator_line(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "REALOWNER")], [])
            (data_dir / "abcd.set").write_text("desc|0||$(14837)|\ntitle|0||-t$(14836)|\n")

            mismatches, skipped = find_operator_mismatches(data_dir)

            self.assertEqual(mismatches, {})
            self.assertEqual(skipped, [SkippedId(id="abcd", reason="missing operator line")])

    def test_multiple_ids_mixed_results(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(
                tmp,
                [
                    _schedlist_line("aaaa", "OWNERA"),
                    _schedlist_line("bbbb", "OWNERB"),
                ],
                [],
            )
            _write_set_file(data_dir, "aaaa", "OWNERA")  # matches
            _write_set_file(data_dir, "bbbb", "STALE")   # mismatch

            mismatches, skipped = find_operator_mismatches(data_dir)

            self.assertEqual(set(mismatches.keys()), {"bbbb"})
            self.assertEqual(skipped, [])


if __name__ == "__main__":
    unittest.main()
