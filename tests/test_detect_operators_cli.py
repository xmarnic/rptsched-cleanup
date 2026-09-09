import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import detect_operators
from tests.fixtures import make_data_dir


def _schedlist_line(template_id, owner):
    return "{}|noverdue|Some Template|n|200207021051|202001010000|{}||||||0|3||0|$<library_notice:c>|ENGLISH|".format(
        template_id, owner
    )


def _write_set_file(data_dir, template_id, operator_value):
    (data_dir / "{}.set".format(template_id)).write_text(
        "# Copyright (c) 1992 - 2000, Sirsi Corporation.\n"
        "desc|0||$(14837)|\n"
        "operator|0||{}|\n"
        "title|0||-t$(14836)|\n".format(operator_value)
    )


class TestDetectOperatorsCli(unittest.TestCase):
    def test_emits_one_record_per_mismatch(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "NEWMGR")], [])
            _write_set_file(data_dir, "abcd", "OLDMGR")

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = detect_operators.main(["--data-dir", str(data_dir)])

            self.assertEqual(exit_code, 0)
            lines = [line for line in out.getvalue().splitlines() if line.strip()]
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["id"], "abcd")
            self.assertEqual(record["old_operator"], "OLDMGR")
            self.assertEqual(record["new_operator"], "NEWMGR")

    def test_no_mismatch_emits_empty_stream(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "SAMEMGR")], [])
            _write_set_file(data_dir, "abcd", "SAMEMGR")

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = detect_operators.main(["--data-dir", str(data_dir)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(out.getvalue().strip(), "")

    def test_skipped_ids_warn_on_stderr_not_in_stream(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "NEWMGR")], [])
            # No .set file written for abcd at all.

            out = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                exit_code = detect_operators.main(["--data-dir", str(data_dir)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(out.getvalue().strip(), "")
            self.assertIn("WARNING", err.getvalue())
            self.assertIn("abcd", err.getvalue())

    def test_does_not_modify_data_dir(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "NEWMGR")], [])
            _write_set_file(data_dir, "abcd", "OLDMGR")
            content_before = (data_dir / "abcd.set").read_text()

            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                detect_operators.main(["--data-dir", str(data_dir)])

            self.assertEqual((data_dir / "abcd.set").read_text(), content_before)


if __name__ == "__main__":
    unittest.main()
