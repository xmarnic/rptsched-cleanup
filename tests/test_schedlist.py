import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rptsched_lib.schedlist import remove_lines, insert_lines
from tests.fixtures import make_data_dir


class TestRemoveLines(unittest.TestCase):
    def test_removes_matching_ids_and_returns_removed_lines_verbatim(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "abcd|noverdue|Keep Me|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
                "wxyz|noverdue|Remove Me|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, [])

            removed = remove_lines(data_dir, {"wxyz"})

            self.assertEqual(removed, [schedlist_lines[1]])
            remaining = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(remaining, [schedlist_lines[0]])

    def test_no_matching_ids_removes_nothing(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "abcd|noverdue|Keep Me|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, [])

            removed = remove_lines(data_dir, {"zzzz"})

            self.assertEqual(removed, [])
            remaining = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(remaining, schedlist_lines)


class TestPermissionsPreserved(unittest.TestCase):
    def test_remove_lines_preserves_schedlist_permissions(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "abcd|noverdue|Keep Me|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
                "wxyz|noverdue|Remove Me|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, [])
            schedlist_path = data_dir / "schedlist"
            os.chmod(str(schedlist_path), 0o640)

            remove_lines(data_dir, {"wxyz"})

            self.assertEqual(oct(os.stat(str(schedlist_path)).st_mode & 0o777), oct(0o640))

    def test_insert_lines_preserves_schedlist_permissions(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "aaaa|noverdue|First|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, [])
            schedlist_path = data_dir / "schedlist"
            os.chmod(str(schedlist_path), 0o644)
            to_insert = [
                "mmmm|noverdue|Middle|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]

            insert_lines(data_dir, to_insert)

            self.assertEqual(oct(os.stat(str(schedlist_path)).st_mode & 0o777), oct(0o644))


class TestInsertLines(unittest.TestCase):
    def test_inserts_missing_lines_at_correct_chronological_position(self):
        # schedlist is ordered by `created` (append order), not by id — ids here
        # are deliberately in the opposite order of `created` so a regression
        # back to id-based sorting would be caught.
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "zzzz|noverdue|First|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
                "aaaa|noverdue|Last|n|200207021053|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, [])
            to_insert = [
                "mmmm|noverdue|Middle|n|200207021052|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]

            result = insert_lines(data_dir, to_insert)

            self.assertEqual(result, {"inserted": 1, "skipped": 0})
            lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(lines, [schedlist_lines[0], to_insert[0], schedlist_lines[1]])

    def test_never_reorders_lines_that_were_not_inserted(self):
        # Existing lines sharing a `created` value with each other must keep
        # their exact original relative order — only newly inserted lines may
        # move, and only relative to their own insertion point.
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "qqkb|itemcntrmod|A|d1|202607250829|202607240831|SOMEMGR||||||0|3||0|||",
                "aswc|assumedlost|B|d1|202607250829|202607240831|SOMEMGR||||||0|3||0|||",
                "hnkw|assumedlost|C|d1|202607250829|202607240831|SOMEMGR||||||0|3||0|||",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, [])

            result = insert_lines(data_dir, [])

            self.assertEqual(result, {"inserted": 0, "skipped": 0})
            lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(lines, schedlist_lines)

    def test_skips_ids_already_present(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "aaaa|noverdue|First|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, [])
            # Same id as an existing line, different content — must not duplicate.
            to_insert = [
                "aaaa|noverdue|Different Content Now|n|200207021051|202001010000|OTHERMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]

            result = insert_lines(data_dir, to_insert)

            self.assertEqual(result, {"inserted": 0, "skipped": 1})
            lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(lines, schedlist_lines)

    def test_second_insert_of_same_lines_is_idempotent(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [], [])
            to_insert = [
                "aaaa|noverdue|First|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]

            insert_lines(data_dir, to_insert)
            result = insert_lines(data_dir, to_insert)

            self.assertEqual(result, {"inserted": 0, "skipped": 1})
            lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(lines, to_insert)


if __name__ == "__main__":
    unittest.main()
