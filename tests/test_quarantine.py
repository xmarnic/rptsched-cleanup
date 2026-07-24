import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rptsched_cleanup.quarantine import make_run_dir


class TestMakeRunDir(unittest.TestCase):
    def test_creates_quarantine_dir_and_run_subfolder(self):
        with TemporaryDirectory() as tmp:
            quarantine_dir = Path(tmp) / "quarantine"
            run_dir = make_run_dir(quarantine_dir, "orphans", "20260724_090000")

            self.assertTrue(run_dir.is_dir())
            self.assertEqual(run_dir, quarantine_dir / "orphans_20260724_090000")

    def test_raises_if_run_dir_already_exists(self):
        with TemporaryDirectory() as tmp:
            quarantine_dir = Path(tmp) / "quarantine"
            make_run_dir(quarantine_dir, "orphans", "20260724_090000")

            with self.assertRaises(FileExistsError):
                make_run_dir(quarantine_dir, "orphans", "20260724_090000")


if __name__ == "__main__":
    unittest.main()
