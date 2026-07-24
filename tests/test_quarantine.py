import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rptsched_cleanup.quarantine import make_run_dir, write_manifest, read_manifest, MANIFEST_FIELDS, move_groups_to_quarantine


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


class TestManifestRoundTrip(unittest.TestCase):
    def test_write_then_read_round_trips_rows(self):
        with TemporaryDirectory() as tmp:
            run_dir = make_run_dir(Path(tmp) / "quarantine", "orphans", "20260724_090000")
            rows = [
                {
                    "id": "abcd",
                    "filename": "abcd.set",
                    "extension": "set",
                    "source_path": str(Path(tmp) / "data" / "abcd.set"),
                    "dest_path": str(run_dir / "abcd.set"),
                    "moved_at": "20260724_090000",
                }
            ]

            manifest_path = write_manifest(run_dir, rows)

            self.assertEqual(manifest_path, run_dir / "manifest.csv")
            self.assertTrue(manifest_path.is_file())

            read_rows = read_manifest(run_dir)
            self.assertEqual(read_rows, rows)

    def test_manifest_fields_order(self):
        self.assertEqual(
            MANIFEST_FIELDS,
            ["id", "filename", "extension", "source_path", "dest_path", "moved_at"],
        )


class TestMoveGroupsSuccess(unittest.TestCase):
    def test_moves_all_files_and_writes_manifest(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            (data_dir / "abcd.set").write_text("set content")
            (data_dir / "abcd.user").write_text("user content")
            (data_dir / "efgh.set").write_text("other set content")

            run_dir = make_run_dir(Path(tmp) / "quarantine", "orphans", "20260724_090000")
            groups = {"abcd": ["abcd.set", "abcd.user"], "efgh": ["efgh.set"]}

            rows = move_groups_to_quarantine(data_dir, run_dir, groups, moved_at="20260724_090000")

            self.assertEqual(len(rows), 3)
            self.assertFalse((data_dir / "abcd.set").exists())
            self.assertFalse((data_dir / "abcd.user").exists())
            self.assertFalse((data_dir / "efgh.set").exists())
            self.assertTrue((run_dir / "abcd.set").is_file())
            self.assertTrue((run_dir / "abcd.user").is_file())
            self.assertTrue((run_dir / "efgh.set").is_file())
            self.assertTrue((run_dir / "manifest.csv").is_file())

            read_rows = read_manifest(run_dir)
            self.assertEqual(read_rows, rows)

            abcd_set_row = next(r for r in rows if r["filename"] == "abcd.set")
            self.assertEqual(abcd_set_row["id"], "abcd")
            self.assertEqual(abcd_set_row["extension"], "set")
            self.assertEqual(abcd_set_row["source_path"], str(data_dir / "abcd.set"))
            self.assertEqual(abcd_set_row["dest_path"], str(run_dir / "abcd.set"))
            self.assertEqual(abcd_set_row["moved_at"], "20260724_090000")


if __name__ == "__main__":
    unittest.main()
