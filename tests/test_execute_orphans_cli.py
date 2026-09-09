import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import execute_orphans
from rptsched_lib.quarantine import read_manifest
from tests.fixtures import make_data_dir

KNOWN_LINE = "abcd|noverdue|Known Template|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"


def _reviewed_file_for(tmp, file_id, filenames):
    record = {"schema_version": 1, "id": file_id, "filenames": filenames}
    path = Path(tmp) / "reviewed.jsonl"
    path.write_text(json.dumps(record) + "\n")
    return path


class TestExecute(unittest.TestCase):
    def test_moves_files_and_writes_manifest(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set", "wxyz.user"])
            quarantine_dir = Path(tmp) / "quarantine"
            reviewed_file = _reviewed_file_for(tmp, "wxyz", ["wxyz.set", "wxyz.user"])

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = execute_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Moved 2 file(s)", out.getvalue())
            self.assertFalse((data_dir / "wxyz.set").exists())
            self.assertFalse((data_dir / "wxyz.user").exists())
            self.assertTrue((data_dir / "abcd.set").exists())

            run_dir = list(quarantine_dir.glob("orphans_*"))[0]
            rows = read_manifest(run_dir)
            self.assertEqual(len(rows), 2)

    def test_aborts_when_file_group_changed_since_review(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            # Reviewed file expected two files; only one exists now.
            reviewed_file = _reviewed_file_for(tmp, "wxyz", ["wxyz.set", "wxyz.user"])

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = execute_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("Refusing to proceed", err.getvalue())
            self.assertTrue((data_dir / "wxyz.set").exists())
            self.assertFalse(quarantine_dir.exists())

    def test_aborts_when_reviewed_id_no_longer_an_orphan(self):
        with TemporaryDirectory() as tmp:
            # wxyz now has a schedlist line -- no longer an orphan.
            data_dir = make_data_dir(
                tmp, [KNOWN_LINE, KNOWN_LINE.replace("abcd", "wxyz")], ["abcd.set", "wxyz.set"],
            )
            quarantine_dir = Path(tmp) / "quarantine"
            reviewed_file = _reviewed_file_for(tmp, "wxyz", ["wxyz.set"])

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = execute_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("no longer an orphan", err.getvalue())

    def test_ignores_new_orphan_not_in_reviewed_file(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set", "qmzk.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            reviewed_file = _reviewed_file_for(tmp, "wxyz", ["wxyz.set"])

            with redirect_stdout(io.StringIO()):
                exit_code = execute_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                ])

            self.assertEqual(exit_code, 0)
            self.assertFalse((data_dir / "wxyz.set").exists())
            self.assertTrue((data_dir / "qmzk.set").exists())

    def test_empty_reviewed_file_does_nothing(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"
            reviewed_file = Path(tmp) / "empty.jsonl"
            reviewed_file.write_text("")

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = execute_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("nothing to do", out.getvalue())
            self.assertFalse(quarantine_dir.exists())


class TestRestore(unittest.TestCase):
    def test_execute_then_restore_round_trips_cleanly(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set", "wxyz.user"])
            quarantine_dir = Path(tmp) / "quarantine"
            reviewed_file = _reviewed_file_for(tmp, "wxyz", ["wxyz.set", "wxyz.user"])

            files_before = sorted(p.name for p in data_dir.iterdir())

            with redirect_stdout(io.StringIO()):
                exit_code = execute_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                ])
            self.assertEqual(exit_code, 0)

            run_dir = list(quarantine_dir.glob("orphans_*"))[0]

            with redirect_stdout(io.StringIO()):
                exit_code = execute_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])
            self.assertEqual(exit_code, 0)

            self.assertEqual(sorted(p.name for p in data_dir.iterdir()), files_before)


if __name__ == "__main__":
    unittest.main()
