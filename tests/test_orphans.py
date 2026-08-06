import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rptsched_lib.orphans import find_orphan_groups
from tests.fixtures import make_data_dir


class TestFindOrphanGroups(unittest.TestCase):
    def test_finds_ids_with_no_schedlist_line(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "abcd|noverdue|Known Template|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            extra_files = [
                "abcd.set", "abcd.selans",  # has a schedlist line -> not an orphan
                "wxyz.set", "wxyz.user",    # no schedlist line -> orphan
                "schedid", "schedid.migr",  # not 4-char-id pattern -> ignored
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, extra_files)

            orphans = find_orphan_groups(data_dir)

            self.assertEqual(set(orphans.keys()), {"wxyz"})
            self.assertEqual(sorted(orphans["wxyz"]), ["wxyz.set", "wxyz.user"])

    def test_no_orphans_returns_empty_dict(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "abcd|noverdue|Known Template|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, ["abcd.set"])

            orphans = find_orphan_groups(data_dir)

            self.assertEqual(orphans, {})


if __name__ == "__main__":
    unittest.main()
