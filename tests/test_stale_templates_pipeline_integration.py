import io
import json
import shutil
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import detect_stale_templates
import execute_stale_templates
import report_stale_templates

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_RPTSCHED_DIR = REPO_ROOT / "rptsched"
LOGS_REPORT_DIR = REPO_ROOT / "logs" / "Report"
# See tests/test_remove_stale_templates_integration.py for why this points at
# an empty Hist dir rather than the real logs/Hist/ pull -- logprint/translate
# aren't available on this dev machine.
EMPTY_HIST_DIR = REPO_ROOT / "logs" / "_empty_hist_for_tests"
if LOGS_REPORT_DIR.is_dir():
    EMPTY_HIST_DIR.mkdir(exist_ok=True)
    (EMPTY_HIST_DIR / (datetime.now().strftime("%Y%m") + ".hist")).touch()


@unittest.skipUnless(
    SAMPLE_RPTSCHED_DIR.is_dir() and LOGS_REPORT_DIR.is_dir(),
    "local rptsched/ and logs/Report/ sample data not present",
)
class TestFullPipelineAgainstSampleData(unittest.TestCase):
    def test_detect_report_execute_restore_round_trip(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = Path(tmp) / "rptsched"
            shutil.copytree(SAMPLE_RPTSCHED_DIR, rptsched_dir)
            quarantine_dir = Path(tmp) / "quarantine"
            cache_path = Path(tmp) / "activity_index_cache.json"
            candidates_path = Path(tmp) / "candidates.jsonl"

            files_before = sorted(p.name for p in rptsched_dir.iterdir() if p.name != "schedlist")
            schedlist_lines_before = sorted((rptsched_dir / "schedlist").read_text().splitlines())

            # Stage 1: detect.
            detect_out = io.StringIO()
            with redirect_stdout(detect_out):
                exit_code = detect_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--logs-report-dir", str(LOGS_REPORT_DIR),
                    "--logs-hist-dir", str(EMPTY_HIST_DIR),
                    "--index-cache-path", str(cache_path),
                ])
            self.assertEqual(exit_code, 0)
            candidates_path.write_text(detect_out.getvalue())
            records = [json.loads(line) for line in detect_out.getvalue().splitlines() if line.strip()]
            self.assertGreater(len(records), 0)

            # detect must not have touched the live rptsched-dir at all.
            self.assertEqual(sorted((rptsched_dir / "schedlist").read_text().splitlines()), schedlist_lines_before)

            # Stage 2: report (human review step -- just confirm it runs
            # cleanly against the same candidate file and rptsched-dir).
            report_out = io.StringIO()
            with redirect_stdout(report_out):
                exit_code = report_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--candidates-file", str(candidates_path),
                ])
            self.assertEqual(exit_code, 0)
            self.assertIn("{} of".format(len(records)), report_out.getvalue())

            # Stage 3: execute against the reviewed file (unmodified --
            # nothing changed since detect, so this must NOT abort).
            execute_out = io.StringIO()
            with redirect_stdout(execute_out):
                exit_code = execute_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(candidates_path),
                    "--logs-report-dir", str(LOGS_REPORT_DIR),
                    "--logs-hist-dir", str(EMPTY_HIST_DIR),
                    "--index-cache-path", str(cache_path),
                ])
            self.assertEqual(exit_code, 0)
            self.assertIn("Moved {} file(s)".format(sum(len(r["filenames"]) for r in records)), execute_out.getvalue())

            run_dir = list(quarantine_dir.glob("templates_*"))[0]
            self.assertTrue((run_dir / "removed_schedlist_lines.txt").is_file())
            self.assertTrue((run_dir / "manifest.csv").is_file())
            remaining_ids = {
                line.split("|")[0] for line in (rptsched_dir / "schedlist").read_text().splitlines() if line.strip()
            }
            self.assertFalse(remaining_ids & {r["id"] for r in records})

            # Stage 4: restore.
            with redirect_stdout(io.StringIO()):
                exit_code = execute_stale_templates.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])
            self.assertEqual(exit_code, 0)

            files_after = sorted(p.name for p in rptsched_dir.iterdir() if p.name != "schedlist")
            schedlist_lines_after = sorted((rptsched_dir / "schedlist").read_text().splitlines())
            self.assertEqual(files_before, files_after)
            self.assertEqual(schedlist_lines_before, schedlist_lines_after)


if __name__ == "__main__":
    unittest.main()
