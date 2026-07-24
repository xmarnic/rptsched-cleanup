import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import run_all


class TestRunAllBase(unittest.TestCase):
    def _patch_all(self, tmp, orphans_code=0, templates_code=0, operators_code=0):
        data_dir = Path(tmp) / "data"
        quarantine_dir = Path(tmp) / "quarantine"
        data_dir.mkdir()

        calls = []

        def fake_orphans(argv):
            calls.append(("orphans", argv))
            print("orphans ran")
            return orphans_code

        def fake_templates(argv):
            calls.append(("templates", argv))
            print("templates ran")
            return templates_code

        def fake_operators(argv):
            calls.append(("operators", argv))
            print("operators ran")
            return operators_code

        patches = [
            patch.object(run_all, "DATA_DIR", data_dir),
            patch.object(run_all, "QUARANTINE_DIR", quarantine_dir),
            patch.object(run_all.remove_orphans, "main", side_effect=fake_orphans),
            patch.object(run_all.remove_stale_templates, "main", side_effect=fake_templates),
            patch.object(run_all.sync_operator_field, "main", side_effect=fake_operators),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        return data_dir, quarantine_dir, calls


class TestRunAll(TestRunAllBase):
    def test_runs_all_three_in_order_with_correct_args(self):
        with TemporaryDirectory() as tmp:
            data_dir, quarantine_dir, calls = self._patch_all(tmp)

            exit_code = run_all.main([])

            self.assertEqual(exit_code, 0)
            self.assertEqual([name for name, _ in calls], ["orphans", "templates", "operators"])
            expected_argv = ["--data-dir", str(data_dir), "--quarantine-dir", str(quarantine_dir)]
            for _, argv in calls:
                self.assertEqual(argv, expected_argv)

    def test_execute_flag_forwarded_to_all_three(self):
        with TemporaryDirectory() as tmp:
            data_dir, quarantine_dir, calls = self._patch_all(tmp)

            exit_code = run_all.main(["--execute"])

            self.assertEqual(exit_code, 0)
            expected_argv = ["--data-dir", str(data_dir), "--quarantine-dir", str(quarantine_dir), "--execute"]
            for _, argv in calls:
                self.assertEqual(argv, expected_argv)

    def test_stops_after_first_failure(self):
        with TemporaryDirectory() as tmp:
            data_dir, quarantine_dir, calls = self._patch_all(tmp, templates_code=1)

            exit_code = run_all.main([])

            self.assertEqual(exit_code, 1)
            self.assertEqual([name for name, _ in calls], ["orphans", "templates"])

    def test_stops_after_first_failure_orphans(self):
        with TemporaryDirectory() as tmp:
            data_dir, quarantine_dir, calls = self._patch_all(tmp, orphans_code=2)

            exit_code = run_all.main([])

            self.assertEqual(exit_code, 2)
            self.assertEqual([name for name, _ in calls], ["orphans"])

    def test_writes_log_file_with_combined_output(self):
        with TemporaryDirectory() as tmp:
            data_dir, quarantine_dir, calls = self._patch_all(tmp)

            run_all.main([])

            log_files = list(quarantine_dir.glob("run_*.log"))
            self.assertEqual(len(log_files), 1)
            content = log_files[0].read_text()
            self.assertIn("orphans ran", content)
            self.assertIn("templates ran", content)
            self.assertIn("operators ran", content)

    def test_quarantine_dir_created_if_missing(self):
        with TemporaryDirectory() as tmp:
            data_dir, quarantine_dir, calls = self._patch_all(tmp)
            self.assertFalse(quarantine_dir.exists())

            run_all.main([])

            self.assertTrue(quarantine_dir.is_dir())

    def test_all_succeed_prints_summary(self):
        with TemporaryDirectory() as tmp:
            data_dir, quarantine_dir, calls = self._patch_all(tmp)

            exit_code = run_all.main([])

            self.assertEqual(exit_code, 0)
            log_files = list(quarantine_dir.glob("run_*.log"))
            content = log_files[0].read_text()
            self.assertIn("successfully", content.lower())


if __name__ == "__main__":
    unittest.main()
