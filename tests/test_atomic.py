import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rptsched_lib.atomic import atomic_write


class TestAtomicWrite(unittest.TestCase):
    def test_writes_content_to_new_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "new_file.txt"

            atomic_write(path, "hello\n")

            self.assertEqual(path.read_text(), "hello\n")

    def test_overwrites_existing_file_content(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing.txt"
            path.write_text("old content")

            atomic_write(path, "new content")

            self.assertEqual(path.read_text(), "new content")

    def test_preserves_permissions_on_existing_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing.txt"
            path.write_text("old content")
            os.chmod(str(path), 0o640)

            atomic_write(path, "new content")

            self.assertEqual(oct(os.stat(str(path)).st_mode & 0o777), oct(0o640))

    def test_no_tmp_file_left_behind_on_success(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing.txt"
            path.write_text("old content")

            atomic_write(path, "new content")

            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["existing.txt"])

    def test_cleans_up_tmp_file_and_reraises_on_replace_failure(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "existing.txt"
            path.write_text("old content")

            with patch("rptsched_lib.atomic.os.replace", side_effect=OSError("simulated failure")):
                with self.assertRaises(OSError):
                    atomic_write(path, "new content")

            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["existing.txt"])
            self.assertEqual(path.read_text(), "old content")


if __name__ == "__main__":
    unittest.main()
