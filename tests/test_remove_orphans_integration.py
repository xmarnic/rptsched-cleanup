import io
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import remove_orphans
from rptsched_cleanup.quarantine import read_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATA_DIR = REPO_ROOT / "rptsched"


@unittest.skipUnless(SAMPLE_DATA_DIR.is_dir(), "local rptsched/ sample data not present")
class TestRemoveOrphansAgainstSampleData(unittest.TestCase):
    def test_dry_run_matches_known_orphan_count(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "rptsched"
            shutil.copytree(SAMPLE_DATA_DIR, data_dir)
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("40 orphan id(s)", out.getvalue())

    def test_execute_then_restore_round_trips_cleanly(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "rptsched"
            shutil.copytree(SAMPLE_DATA_DIR, data_dir)
            quarantine_dir = Path(tmp) / "quarantine"

            files_before = sorted(p.name for p in data_dir.iterdir())

            with redirect_stdout(io.StringIO()):
                remove_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            run_dir = list(quarantine_dir.glob("orphans_*"))[0]
            rows = read_manifest(run_dir)
            self.assertGreater(len(rows), 0)

            with redirect_stdout(io.StringIO()):
                remove_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            files_after = sorted(p.name for p in data_dir.iterdir())
            self.assertEqual(files_before, files_after)


if __name__ == "__main__":
    unittest.main()
