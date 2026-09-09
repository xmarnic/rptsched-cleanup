import os
import unittest
from pathlib import Path
from unittest.mock import patch

from rptsched_lib.cli import default_work_dir, unicorn_paths, unicorn_root_default


class TestDefaultWorkDir(unittest.TestCase):
    def test_is_anchored_under_home_not_cwd(self):
        work_dir = default_work_dir("stale_templates")

        self.assertTrue(work_dir.is_absolute())
        self.assertTrue(str(work_dir).startswith(str(Path.home())))

    def test_distinct_per_category(self):
        self.assertNotEqual(default_work_dir("orphans"), default_work_dir("operators"))

    def test_same_category_is_stable_across_calls(self):
        # Simulates the exact failure mode this exists to prevent: two
        # separate invocations (e.g. detect now, execute days later,
        # possibly after re-extracting the tool into a new directory)
        # must resolve to the same work-dir regardless of cwd.
        self.assertEqual(default_work_dir("stale_templates"), default_work_dir("stale_templates"))


class TestUnicornPaths(unittest.TestCase):
    def test_derives_all_three_standard_subpaths(self):
        rptsched_dir, logs_report_dir, logs_hist_dir = unicorn_paths("/software/WYLD/Unicorn")

        self.assertEqual(rptsched_dir, Path("/software/WYLD/Unicorn/Rptsched"))
        self.assertEqual(logs_report_dir, Path("/software/WYLD/Unicorn/Logs/Report"))
        self.assertEqual(logs_hist_dir, Path("/software/WYLD/Unicorn/Logs/Hist"))


class TestUnicornRootDefault(unittest.TestCase):
    def test_reads_env_var(self):
        with patch.dict(os.environ, {"RPTSCHED_UNICORN_ROOT": "/some/root"}):
            self.assertEqual(unicorn_root_default(), "/some/root")

    def test_none_when_env_var_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RPTSCHED_UNICORN_ROOT", None)
            self.assertIsNone(unicorn_root_default())


if __name__ == "__main__":
    unittest.main()
