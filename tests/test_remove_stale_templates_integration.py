import io
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import remove_stale_templates
from rptsched_lib.templates import find_stale_template_candidates

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATA_DIR = REPO_ROOT / "rptsched"


@unittest.skipUnless(SAMPLE_DATA_DIR.is_dir(), "local rptsched/ sample data not present")
class TestRemoveStaleTemplatesAgainstSampleData(unittest.TestCase):
    def test_dry_run_matches_candidate_count(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "rptsched"
            shutil.copytree(SAMPLE_DATA_DIR, data_dir)
            quarantine_dir = Path(tmp) / "quarantine"

            # Computed independently, moments before the CLI call, using the
            # same default years=3 / today=now() as the CLI — not hardcoded,
            # since the exact count shifts by run date (some lines sit right
            # at the 3-year boundary).
            expected = find_stale_template_candidates(data_dir, years=3)
            self.assertGreater(len(expected), 0)

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("{} stale template(s)".format(len(expected)), out.getvalue())
            self.assertFalse(quarantine_dir.exists())

    def test_execute_then_restore_round_trips_cleanly(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "rptsched"
            shutil.copytree(SAMPLE_DATA_DIR, data_dir)
            quarantine_dir = Path(tmp) / "quarantine"

            files_before = sorted(p.name for p in data_dir.iterdir() if p.name != "schedlist")
            schedlist_lines_before = sorted((data_dir / "schedlist").read_text().splitlines())

            with redirect_stdout(io.StringIO()):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])
            self.assertEqual(exit_code, 0)

            run_dir = list(quarantine_dir.glob("templates_*"))[0]
            self.assertTrue((run_dir / "removed_schedlist_lines.txt").is_file())
            self.assertTrue((run_dir / "manifest.csv").is_file())

            with redirect_stdout(io.StringIO()):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])
            self.assertEqual(exit_code, 0)

            files_after = sorted(p.name for p in data_dir.iterdir() if p.name != "schedlist")
            schedlist_lines_after = sorted((data_dir / "schedlist").read_text().splitlines())

            self.assertEqual(files_before, files_after)
            self.assertEqual(schedlist_lines_before, schedlist_lines_after)
            # manifest and removed-lines record survive restore
            self.assertTrue((run_dir / "manifest.csv").is_file())
            self.assertTrue((run_dir / "removed_schedlist_lines.txt").is_file())


if __name__ == "__main__":
    unittest.main()
