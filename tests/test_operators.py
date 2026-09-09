import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rptsched_lib.operators import (
    find_operator_mismatches,
    OperatorMismatch,
    SkippedId,
    read_operator,
    read_schedlist_owners,
    rewrite_operator,
    MissingOperatorLineError,
    write_operator_manifest,
    read_operator_manifest,
    apply_mismatches,
    apply_reviewed_changes,
    classify_current_value,
    OperatorRewriteError,
    MANIFEST_FIELDS,
)
from rptsched_lib.quarantine import make_run_dir
from tests.fixtures import make_rptsched_dir


def _schedlist_line(template_id, owner):
    return "{}|noverdue|Some Template|n|200207021051|202001010000|{}||||||0|3||0|$<library_notice:c>|ENGLISH|".format(
        template_id, owner
    )


def _write_set_file(rptsched_dir, template_id, operator_value, middle_field=""):
    (rptsched_dir / "{}.set".format(template_id)).write_text(
        "# Copyright (c) 1992 - 2000, Sirsi Corporation.\n"
        "desc|0||$(14837)|\n"
        "operator|0|{}|{}|\n"
        "title|0||-t$(14836)|\n".format(middle_field, operator_value)
    )


class TestFindOperatorMismatches(unittest.TestCase):
    def test_detects_mismatch(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [_schedlist_line("abcd", "REALOWNER")], [])
            _write_set_file(rptsched_dir, "abcd", "STALEOWNER")

            mismatches, skipped = find_operator_mismatches(rptsched_dir)

            self.assertEqual(skipped, [])
            self.assertEqual(
                mismatches,
                {"abcd": OperatorMismatch(id="abcd", old_operator="STALEOWNER", new_operator="REALOWNER")},
            )

    def test_no_mismatch_when_operator_matches_owner(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [_schedlist_line("abcd", "SAMEOWNER")], [])
            _write_set_file(rptsched_dir, "abcd", "SAMEOWNER")

            mismatches, skipped = find_operator_mismatches(rptsched_dir)

            self.assertEqual(mismatches, {})
            self.assertEqual(skipped, [])

    def test_comparison_is_case_sensitive(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [_schedlist_line("abcd", "WRIGCIRCMGR")], [])
            _write_set_file(rptsched_dir, "abcd", "wrigcircmgr")

            mismatches, skipped = find_operator_mismatches(rptsched_dir)

            self.assertEqual(
                mismatches,
                {"abcd": OperatorMismatch(id="abcd", old_operator="wrigcircmgr", new_operator="WRIGCIRCMGR")},
            )

    def test_middle_field_is_not_compared_or_touched_by_detection(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [_schedlist_line("jiqi", "SIRSI")], [])
            _write_set_file(rptsched_dir, "jiqi", "SIRSI", middle_field="SIRSI")

            mismatches, skipped = find_operator_mismatches(rptsched_dir)

            self.assertEqual(mismatches, {})

    def test_skips_id_with_no_matching_set_file(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [_schedlist_line("abcd", "REALOWNER")], [])
            # no abcd.set written at all

            mismatches, skipped = find_operator_mismatches(rptsched_dir)

            self.assertEqual(mismatches, {})
            self.assertEqual(skipped, [SkippedId(id="abcd", reason="missing .set file")])

    def test_skips_id_with_no_operator_line(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [_schedlist_line("abcd", "REALOWNER")], [])
            (rptsched_dir / "abcd.set").write_text("desc|0||$(14837)|\ntitle|0||-t$(14836)|\n")

            mismatches, skipped = find_operator_mismatches(rptsched_dir)

            self.assertEqual(mismatches, {})
            self.assertEqual(skipped, [SkippedId(id="abcd", reason="missing operator line")])

    def test_multiple_ids_mixed_results(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(
                tmp,
                [
                    _schedlist_line("aaaa", "OWNERA"),
                    _schedlist_line("bbbb", "OWNERB"),
                ],
                [],
            )
            _write_set_file(rptsched_dir, "aaaa", "OWNERA")  # matches
            _write_set_file(rptsched_dir, "bbbb", "STALE")   # mismatch

            mismatches, skipped = find_operator_mismatches(rptsched_dir)

            self.assertEqual(set(mismatches.keys()), {"bbbb"})
            self.assertEqual(skipped, [])


class TestReadOperator(unittest.TestCase):
    def test_reads_current_operator_value(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = Path(tmp)
            _write_set_file(rptsched_dir, "abcd", "SOMEOWNER")

            self.assertEqual(read_operator(rptsched_dir, "abcd"), "SOMEOWNER")

    def test_returns_none_for_missing_set_file(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = Path(tmp)

            self.assertIsNone(read_operator(rptsched_dir, "abcd"))


class TestRewriteOperator(unittest.TestCase):
    def test_rewrites_only_the_operator_value_field(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = Path(tmp)
            _write_set_file(rptsched_dir, "abcd", "OLDVALUE", middle_field="SIRSI")

            rewrite_operator(rptsched_dir, "abcd", "NEWVALUE")

            content = (rptsched_dir / "abcd.set").read_text()
            self.assertIn("operator|0|SIRSI|NEWVALUE|", content)
            self.assertNotIn("OLDVALUE", content)
            # other lines untouched
            self.assertIn("desc|0||$(14837)|", content)
            self.assertIn("title|0||-t$(14836)|", content)

    def test_rewrite_is_atomic_no_tmp_file_left_behind(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = Path(tmp)
            _write_set_file(rptsched_dir, "abcd", "OLDVALUE")

            rewrite_operator(rptsched_dir, "abcd", "NEWVALUE")

            remaining = list(rptsched_dir.iterdir())
            self.assertEqual([p.name for p in remaining], ["abcd.set"])

    def test_raises_when_no_operator_line_present(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = Path(tmp)
            (rptsched_dir / "abcd.set").write_text("desc|0||$(14837)|\n")

            with self.assertRaises(MissingOperatorLineError):
                rewrite_operator(rptsched_dir, "abcd", "NEWVALUE")


class TestManifestRoundTrip(unittest.TestCase):
    def test_write_then_read_round_trips_rows(self):
        with TemporaryDirectory() as tmp:
            run_dir = make_run_dir(Path(tmp) / "quarantine", "operators", "20260724_090000")
            rows = [{"id": "abcd", "old_operator": "OLD", "new_operator": "NEW"}]

            manifest_path = write_operator_manifest(run_dir, rows)

            self.assertEqual(manifest_path, run_dir / "manifest.csv")
            self.assertEqual(read_operator_manifest(run_dir), rows)

    def test_manifest_fields_order(self):
        self.assertEqual(MANIFEST_FIELDS, ["id", "old_operator", "new_operator"])


class TestApplyMismatches(unittest.TestCase):
    def test_rewrites_all_and_writes_manifest(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = Path(tmp) / "data"
            rptsched_dir.mkdir()
            _write_set_file(rptsched_dir, "aaaa", "OLDA")
            _write_set_file(rptsched_dir, "bbbb", "OLDB")
            run_dir = make_run_dir(Path(tmp) / "quarantine", "operators", "20260724_090000")

            mismatches = {
                "aaaa": OperatorMismatch("aaaa", "OLDA", "NEWA"),
                "bbbb": OperatorMismatch("bbbb", "OLDB", "NEWB"),
            }

            rows = apply_mismatches(rptsched_dir, run_dir, mismatches)

            self.assertEqual(read_operator(rptsched_dir, "aaaa"), "NEWA")
            self.assertEqual(read_operator(rptsched_dir, "bbbb"), "NEWB")
            self.assertEqual(len(rows), 2)
            self.assertEqual(read_operator_manifest(run_dir), rows)

    def test_aborts_and_writes_partial_manifest_on_failure(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = Path(tmp) / "data"
            rptsched_dir.mkdir()
            _write_set_file(rptsched_dir, "aaaa", "OLDA")
            _write_set_file(rptsched_dir, "bbbb", "OLDB")
            run_dir = make_run_dir(Path(tmp) / "quarantine", "operators", "20260724_090000")

            mismatches = {
                "aaaa": OperatorMismatch("aaaa", "OLDA", "NEWA"),
                "bbbb": OperatorMismatch("bbbb", "OLDB", "NEWB"),
            }

            with patch("rptsched_lib.atomic.os.replace", side_effect=OSError("simulated failure")):
                with self.assertRaises(OperatorRewriteError):
                    apply_mismatches(rptsched_dir, run_dir, mismatches)

            # manifest reflects zero completed rewrites (aaaa sorts first and fails immediately)
            self.assertEqual(read_operator_manifest(run_dir), [])
            # original files untouched (atomic write failed before replace)
            self.assertEqual(read_operator(rptsched_dir, "aaaa"), "OLDA")

    def test_manifest_contains_only_rows_completed_before_failure(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = Path(tmp) / "data"
            rptsched_dir.mkdir()
            _write_set_file(rptsched_dir, "aaaa", "OLDA")
            _write_set_file(rptsched_dir, "bbbb", "OLDB")
            _write_set_file(rptsched_dir, "cccc", "OLDC")
            run_dir = make_run_dir(Path(tmp) / "quarantine", "operators", "20260724_090000")

            mismatches = {
                "aaaa": OperatorMismatch("aaaa", "OLDA", "NEWA"),
                "bbbb": OperatorMismatch("bbbb", "OLDB", "NEWB"),
                "cccc": OperatorMismatch("cccc", "OLDC", "NEWC"),
            }

            real_replace = os.replace
            calls = {"count": 0}

            def flaky_replace(*args, **kwargs):
                calls["count"] += 1
                if calls["count"] >= 3:
                    raise OSError("simulated failure on third rewrite")
                return real_replace(*args, **kwargs)

            with patch("rptsched_lib.atomic.os.replace", side_effect=flaky_replace):
                with self.assertRaises(OperatorRewriteError):
                    apply_mismatches(rptsched_dir, run_dir, mismatches)

            # aaaa and bbbb (sorted first) succeeded before cccc failed
            self.assertEqual(
                read_operator_manifest(run_dir),
                [
                    {"id": "aaaa", "old_operator": "OLDA", "new_operator": "NEWA"},
                    {"id": "bbbb", "old_operator": "OLDB", "new_operator": "NEWB"},
                ],
            )
            self.assertEqual(read_operator(rptsched_dir, "aaaa"), "NEWA")
            self.assertEqual(read_operator(rptsched_dir, "bbbb"), "NEWB")
            self.assertEqual(read_operator(rptsched_dir, "cccc"), "OLDC")


class TestReadSchedlistOwners(unittest.TestCase):
    def test_returns_id_to_owner_mapping(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = Path(tmp)
            rptsched_dir.mkdir(exist_ok=True)
            (rptsched_dir / "schedlist").write_text(_schedlist_line("abcd", "SOMEMGR") + "\n")

            self.assertEqual(read_schedlist_owners(rptsched_dir), {"abcd": "SOMEMGR"})


class TestClassifyCurrentValue(unittest.TestCase):
    def test_matches_old(self):
        self.assertEqual(classify_current_value("OLD", "OLD", "NEW"), "matches_old")

    def test_matches_new(self):
        self.assertEqual(classify_current_value("NEW", "OLD", "NEW"), "matches_new")

    def test_conflict(self):
        self.assertEqual(classify_current_value("SOMETHING_ELSE", "OLD", "NEW"), "conflict")


class TestApplyReviewedChanges(unittest.TestCase):
    def test_rewrites_matches_old_and_records_matches_new_without_rewriting(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = Path(tmp) / "data"
            rptsched_dir.mkdir()
            _write_set_file(rptsched_dir, "aaaa", "OLDA")
            _write_set_file(rptsched_dir, "bbbb", "NEWB")  # already applied
            run_dir = make_run_dir(Path(tmp) / "quarantine", "operators", "20260724_090000")

            reviewed = {
                "aaaa": {"id": "aaaa", "old_operator": "OLDA", "new_operator": "NEWA"},
                "bbbb": {"id": "bbbb", "old_operator": "OLDB", "new_operator": "NEWB"},
            }
            classifications = {"aaaa": "matches_old", "bbbb": "matches_new"}

            rows = apply_reviewed_changes(rptsched_dir, run_dir, reviewed, classifications)

            self.assertEqual(read_operator(rptsched_dir, "aaaa"), "NEWA")
            self.assertEqual(read_operator(rptsched_dir, "bbbb"), "NEWB")
            self.assertEqual(len(rows), 2)
            self.assertEqual(read_operator_manifest(run_dir), rows)


if __name__ == "__main__":
    unittest.main()
