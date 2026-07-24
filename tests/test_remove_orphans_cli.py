import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import remove_orphans
from tests.fixtures import make_data_dir


class TestDryRun(unittest.TestCase):
    def test_dry_run_reports_orphans_and_changes_nothing(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "abcd|noverdue|Known Template|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, ["abcd.set", "wxyz.set", "wxyz.user"])
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("wxyz", out.getvalue())
            self.assertFalse(quarantine_dir.exists())
            self.assertTrue((data_dir / "wxyz.set").exists())
            self.assertTrue((data_dir / "wxyz.user").exists())

    def test_missing_required_args_errors(self):
        with self.assertRaises(SystemExit):
            remove_orphans.main([])


if __name__ == "__main__":
    unittest.main()
