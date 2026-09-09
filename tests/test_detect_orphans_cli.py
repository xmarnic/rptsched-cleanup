import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import detect_orphans
from tests.fixtures import make_rptsched_dir

KNOWN_LINE = "abcd|noverdue|Known Template|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"


class TestDetectOrphansCli(unittest.TestCase):
    def test_emits_one_jsonl_record_per_orphan(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set", "wxyz.user"])

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = detect_orphans.main(["--rptsched-dir", str(rptsched_dir)])

            self.assertEqual(exit_code, 0)
            lines = [line for line in out.getvalue().splitlines() if line.strip()]
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["id"], "wxyz")
            self.assertEqual(sorted(record["filenames"]), ["wxyz.set", "wxyz.user"])
            self.assertIn("schema_version", record)

    def test_does_not_modify_rptsched_dir(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [KNOWN_LINE], ["abcd.set", "wxyz.set"])
            files_before = sorted(p.name for p in rptsched_dir.iterdir())

            with redirect_stdout(io.StringIO()):
                detect_orphans.main(["--rptsched-dir", str(rptsched_dir)])

            self.assertEqual(sorted(p.name for p in rptsched_dir.iterdir()), files_before)

    def test_no_orphans_emits_empty_stream(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [KNOWN_LINE], ["abcd.set"])

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = detect_orphans.main(["--rptsched-dir", str(rptsched_dir)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(out.getvalue().strip(), "")


if __name__ == "__main__":
    unittest.main()
