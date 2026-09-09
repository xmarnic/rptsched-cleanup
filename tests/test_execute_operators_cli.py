import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import execute_operators
from rptsched_lib.operators import read_operator
from tests.fixtures import make_rptsched_dir


def _schedlist_line(template_id, owner):
    return "{}|noverdue|Some Template|n|200207021051|202001010000|{}||||||0|3||0|$<library_notice:c>|ENGLISH|".format(
        template_id, owner
    )


def _write_set_file(rptsched_dir, template_id, operator_value):
    (rptsched_dir / "{}.set".format(template_id)).write_text(
        "# Copyright (c) 1992 - 2000, Sirsi Corporation.\n"
        "desc|0||$(14837)|\n"
        "operator|0||{}|\n"
        "title|0||-t$(14836)|\n".format(operator_value)
    )


def _reviewed_file_for(tmp, template_id, old_operator, new_operator):
    record = {"schema_version": 1, "id": template_id, "old_operator": old_operator, "new_operator": new_operator}
    path = Path(tmp) / "reviewed.jsonl"
    path.write_text(json.dumps(record) + "\n")
    return path


class TestExecute(unittest.TestCase):
    def test_applies_reviewed_change_and_writes_manifest(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [_schedlist_line("abcd", "NEWMGR")], [])
            _write_set_file(rptsched_dir, "abcd", "OLDMGR")
            quarantine_dir = Path(tmp) / "quarantine"
            reviewed_file = _reviewed_file_for(tmp, "abcd", "OLDMGR", "NEWMGR")

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = execute_operators.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Corrected 1 operator value(s)", out.getvalue())
            self.assertEqual(read_operator(rptsched_dir, "abcd"), "NEWMGR")

    def test_idempotent_when_already_applied(self):
        # Simulates an interrupted prior run: the .set file already shows
        # new_operator, even though this is a fresh execute invocation.
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [_schedlist_line("abcd", "NEWMGR")], [])
            _write_set_file(rptsched_dir, "abcd", "NEWMGR")
            quarantine_dir = Path(tmp) / "quarantine"
            reviewed_file = _reviewed_file_for(tmp, "abcd", "OLDMGR", "NEWMGR")

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = execute_operators.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Corrected 1 operator value(s)", out.getvalue())
            self.assertEqual(read_operator(rptsched_dir, "abcd"), "NEWMGR")

    def test_aborts_when_schedlist_owner_changed_since_review(self):
        with TemporaryDirectory() as tmp:
            # Reviewed expected new_operator=NEWMGR, but schedlist owner is
            # now something else entirely.
            rptsched_dir = make_rptsched_dir(tmp, [_schedlist_line("abcd", "THIRDMGR")], [])
            _write_set_file(rptsched_dir, "abcd", "OLDMGR")
            quarantine_dir = Path(tmp) / "quarantine"
            reviewed_file = _reviewed_file_for(tmp, "abcd", "OLDMGR", "NEWMGR")

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = execute_operators.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("Refusing to proceed", err.getvalue())
            self.assertEqual(read_operator(rptsched_dir, "abcd"), "OLDMGR")
            self.assertFalse(quarantine_dir.exists())

    def test_aborts_on_conflicting_current_operator_value(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [_schedlist_line("abcd", "NEWMGR")], [])
            # Current operator matches neither reviewed old nor new.
            _write_set_file(rptsched_dir, "abcd", "SOMEONEELSEMGR")
            quarantine_dir = Path(tmp) / "quarantine"
            reviewed_file = _reviewed_file_for(tmp, "abcd", "OLDMGR", "NEWMGR")

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = execute_operators.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("Refusing to proceed", err.getvalue())
            self.assertEqual(read_operator(rptsched_dir, "abcd"), "SOMEONEELSEMGR")

    def test_empty_reviewed_file_does_nothing(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [_schedlist_line("abcd", "NEWMGR")], [])
            _write_set_file(rptsched_dir, "abcd", "OLDMGR")
            quarantine_dir = Path(tmp) / "quarantine"
            reviewed_file = Path(tmp) / "empty.jsonl"
            reviewed_file.write_text("")

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = execute_operators.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("nothing to do", out.getvalue())
            self.assertFalse(quarantine_dir.exists())


class TestRestore(unittest.TestCase):
    def test_execute_then_restore_round_trips_cleanly(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [_schedlist_line("abcd", "NEWMGR")], [])
            _write_set_file(rptsched_dir, "abcd", "OLDMGR")
            quarantine_dir = Path(tmp) / "quarantine"
            reviewed_file = _reviewed_file_for(tmp, "abcd", "OLDMGR", "NEWMGR")

            with redirect_stdout(io.StringIO()):
                exit_code = execute_operators.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                ])
            self.assertEqual(exit_code, 0)
            self.assertEqual(read_operator(rptsched_dir, "abcd"), "NEWMGR")

            run_dir = list(quarantine_dir.glob("operators_*"))[0]

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = execute_operators.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Restored 1 operator value(s)", out.getvalue())
            self.assertEqual(read_operator(rptsched_dir, "abcd"), "OLDMGR")

    def test_second_restore_is_idempotent(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [_schedlist_line("abcd", "NEWMGR")], [])
            _write_set_file(rptsched_dir, "abcd", "OLDMGR")
            quarantine_dir = Path(tmp) / "quarantine"
            reviewed_file = _reviewed_file_for(tmp, "abcd", "OLDMGR", "NEWMGR")

            with redirect_stdout(io.StringIO()):
                execute_operators.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                ])
            run_dir = list(quarantine_dir.glob("operators_*"))[0]

            with redirect_stdout(io.StringIO()):
                execute_operators.main([
                    "--rptsched-dir", str(rptsched_dir), "--quarantine-dir", str(quarantine_dir), "--restore", str(run_dir),
                ])

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = execute_operators.main([
                    "--rptsched-dir", str(rptsched_dir), "--quarantine-dir", str(quarantine_dir), "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("skipped 1 already-restored", out.getvalue())

    def test_restore_conflict_aborts(self):
        with TemporaryDirectory() as tmp:
            rptsched_dir = make_rptsched_dir(tmp, [_schedlist_line("abcd", "NEWMGR")], [])
            _write_set_file(rptsched_dir, "abcd", "OLDMGR")
            quarantine_dir = Path(tmp) / "quarantine"
            reviewed_file = _reviewed_file_for(tmp, "abcd", "OLDMGR", "NEWMGR")

            with redirect_stdout(io.StringIO()):
                execute_operators.main([
                    "--rptsched-dir", str(rptsched_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--candidates-file", str(reviewed_file),
                ])
            run_dir = list(quarantine_dir.glob("operators_*"))[0]

            # Someone else changed the operator value after execute, before restore.
            _write_set_file(rptsched_dir, "abcd", "THIRDMGR")

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = execute_operators.main([
                    "--rptsched-dir", str(rptsched_dir), "--quarantine-dir", str(quarantine_dir), "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("Cannot restore", err.getvalue())


if __name__ == "__main__":
    unittest.main()
