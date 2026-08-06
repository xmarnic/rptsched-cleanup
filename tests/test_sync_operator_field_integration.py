import io
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import sync_operator_field
from rptsched_lib.operators import find_operator_mismatches

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATA_DIR = REPO_ROOT / "rptsched"


@unittest.skipUnless(SAMPLE_DATA_DIR.is_dir(), "local rptsched/ sample data not present")
class TestSyncOperatorFieldAgainstSampleData(unittest.TestCase):
    def test_dry_run_matches_mismatch_count(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "rptsched"
            shutil.copytree(SAMPLE_DATA_DIR, data_dir)
            quarantine_dir = Path(tmp) / "quarantine"

            expected, _skipped = find_operator_mismatches(data_dir)
            self.assertGreater(len(expected), 0)

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("{} operator mismatch(es)".format(len(expected)), out.getvalue())
            self.assertFalse(quarantine_dir.exists())

    def test_execute_then_restore_round_trips_cleanly(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "rptsched"
            shutil.copytree(SAMPLE_DATA_DIR, data_dir)
            quarantine_dir = Path(tmp) / "quarantine"

            set_files_before = {
                p.name: p.read_text()
                for p in data_dir.iterdir()
                if p.suffix == ".set"
            }

            with redirect_stdout(io.StringIO()):
                exit_code = sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])
            self.assertEqual(exit_code, 0)

            run_dir = list(quarantine_dir.glob("operators_*"))[0]
            self.assertTrue((run_dir / "manifest.csv").is_file())

            # after execute, no mismatches should remain
            remaining, _skipped = find_operator_mismatches(data_dir)
            self.assertEqual(remaining, {})

            with redirect_stdout(io.StringIO()):
                exit_code = sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])
            self.assertEqual(exit_code, 0)

            set_files_after = {
                p.name: p.read_text()
                for p in data_dir.iterdir()
                if p.suffix == ".set"
            }
            self.assertEqual(set_files_before, set_files_after)
            self.assertTrue((run_dir / "manifest.csv").is_file())


if __name__ == "__main__":
    unittest.main()
