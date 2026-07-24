import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rptsched_cleanup.schedlist import remove_lines, insert_lines
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


class TestInsertLines(unittest.TestCase):
    def test_inserts_missing_lines_and_sorts_by_id(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "aaaa|noverdue|First|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
                "zzzz|noverdue|Last|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, [])
            to_insert = [
                "mmmm|noverdue|Middle|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]

            result = insert_lines(data_dir, to_insert)

            self.assertEqual(result, {"inserted": 1, "skipped": 0})
            lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(lines, [schedlist_lines[0], to_insert[0], schedlist_lines[1]])

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
