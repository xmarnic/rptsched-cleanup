import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rptsched_lib.quarantine import (
    make_run_dir, write_manifest, read_manifest, MANIFEST_FIELDS, move_groups_to_quarantine,
    QuarantineMoveError, restore_run, QuarantineRestoreError, InvalidManifestError,
)


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

    def test_write_and_read_accept_custom_fieldnames(self):
        with TemporaryDirectory() as tmp:
            run_dir = make_run_dir(Path(tmp) / "quarantine", "operators", "20260724_090000")
            custom_fields = ["id", "old_value", "new_value"]
            rows = [{"id": "abcd", "old_value": "OLD", "new_value": "NEW"}]

            write_manifest(run_dir, rows, fieldnames=custom_fields)

            self.assertEqual(read_manifest(run_dir, fieldnames=custom_fields), rows)

    def test_read_raises_on_column_mismatch(self):
        with TemporaryDirectory() as tmp:
            run_dir = make_run_dir(Path(tmp) / "quarantine", "operators", "20260724_090000")
            write_manifest(run_dir, [{"id": "abcd", "old_value": "OLD", "new_value": "NEW"}],
                            fieldnames=["id", "old_value", "new_value"])

            with self.assertRaises(InvalidManifestError):
                read_manifest(run_dir)


class TestMoveGroupsSuccess(unittest.TestCase):
    def test_moves_all_files_and_writes_manifest(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = Path(tmp) / "data"
            rptsched_dir.mkdir()
            (rptsched_dir / "abcd.set").write_text("set content")
            (rptsched_dir / "abcd.user").write_text("user content")
            (rptsched_dir / "efgh.set").write_text("other set content")

            run_dir = make_run_dir(Path(tmp) / "quarantine", "orphans", "20260724_090000")
            groups = {"abcd": ["abcd.set", "abcd.user"], "efgh": ["efgh.set"]}

            rows = move_groups_to_quarantine(rptsched_dir, run_dir, groups, moved_at="20260724_090000")

            self.assertEqual(len(rows), 3)
            self.assertFalse((rptsched_dir / "abcd.set").exists())
            self.assertFalse((rptsched_dir / "abcd.user").exists())
            self.assertFalse((rptsched_dir / "efgh.set").exists())
            self.assertTrue((run_dir / "abcd.set").is_file())
            self.assertTrue((run_dir / "abcd.user").is_file())
            self.assertTrue((run_dir / "efgh.set").is_file())
            self.assertTrue((run_dir / "manifest.csv").is_file())

            read_rows = read_manifest(run_dir)
            self.assertEqual(read_rows, rows)

            abcd_set_row = next(r for r in rows if r["filename"] == "abcd.set")
            self.assertEqual(abcd_set_row["id"], "abcd")
            self.assertEqual(abcd_set_row["extension"], "set")
            self.assertEqual(abcd_set_row["source_path"], str(rptsched_dir / "abcd.set"))
            self.assertEqual(abcd_set_row["dest_path"], str(run_dir / "abcd.set"))
            self.assertEqual(abcd_set_row["moved_at"], "20260724_090000")


class TestMoveGroupsAbortOnFailure(unittest.TestCase):
    def test_aborts_and_writes_partial_manifest_on_move_failure(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = Path(tmp) / "data"
            rptsched_dir.mkdir()
            (rptsched_dir / "abcd.set").write_text("set content")
            (rptsched_dir / "efgh.set").write_text("other set content")

            run_dir = make_run_dir(Path(tmp) / "quarantine", "orphans", "20260724_090000")
            groups = {"abcd": ["abcd.set"], "efgh": ["efgh.set"]}

            real_move = shutil.move

            def fail_on_efgh(src, dst):
                if "efgh" in src:
                    raise OSError("simulated failure moving efgh.set")
                return real_move(src, dst)

            with patch("rptsched_lib.quarantine.shutil.move", side_effect=fail_on_efgh):
                with self.assertRaises(QuarantineMoveError):
                    move_groups_to_quarantine(rptsched_dir, run_dir, groups, moved_at="20260724_090000")

            # abcd moved (sorts before efgh), efgh did not
            self.assertFalse((rptsched_dir / "abcd.set").exists())
            self.assertTrue((run_dir / "abcd.set").is_file())
            self.assertTrue((rptsched_dir / "efgh.set").exists())
            self.assertFalse((run_dir / "efgh.set").exists())

            # manifest reflects only the successful move
            rows = read_manifest(run_dir)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["filename"], "abcd.set")


class TestRestoreRun(unittest.TestCase):
    def _setup_run(self, tmp):
        rptsched_dir = Path(tmp) / "data"
        rptsched_dir.mkdir()
        (rptsched_dir / "abcd.set").write_text("set content")
        (rptsched_dir / "efgh.set").write_text("other set content")

        run_dir = make_run_dir(Path(tmp) / "quarantine", "orphans", "20260724_090000")
        groups = {"abcd": ["abcd.set"], "efgh": ["efgh.set"]}
        move_groups_to_quarantine(rptsched_dir, run_dir, groups, moved_at="20260724_090000")
        return rptsched_dir, run_dir

    def test_restores_all_files(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir, run_dir = self._setup_run(tmp)

            result = restore_run(run_dir)

            self.assertEqual(result, {"restored": 2, "skipped": 0})
            self.assertTrue((rptsched_dir / "abcd.set").is_file())
            self.assertTrue((rptsched_dir / "efgh.set").is_file())
            self.assertFalse((run_dir / "abcd.set").exists())
            self.assertFalse((run_dir / "efgh.set").exists())
            # manifest is never deleted
            self.assertTrue((run_dir / "manifest.csv").is_file())

    def test_second_restore_is_idempotent_no_op(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir, run_dir = self._setup_run(tmp)
            restore_run(run_dir)

            result = restore_run(run_dir)

            self.assertEqual(result, {"restored": 0, "skipped": 2})

    def test_refuses_to_overwrite_existing_source(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir, run_dir = self._setup_run(tmp)
            # something now occupies abcd.set's original path
            (rptsched_dir / "abcd.set").write_text("someone else's file")

            with self.assertRaises(QuarantineRestoreError):
                restore_run(run_dir)

            # efgh.set (processed after abcd.set) must be untouched
            self.assertTrue((run_dir / "efgh.set").is_file())


if __name__ == "__main__":
    unittest.main()
