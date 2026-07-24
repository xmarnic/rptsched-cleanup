# sync_operator_field Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `sync_operator_field.py`, a CLI script that corrects `<id>.set` files whose `operator` field has drifted out of sync with `schedlist`'s owner field, following the dry-run/`--execute`/`--restore` pattern of the existing `remove_orphans.py` / `remove_stale_templates.py` scripts.

**Architecture:** One new module, `rptsched_cleanup/operators.py`, holds mismatch detection, single-line `.set` rewriting (temp-file + atomic rename, mirroring `rptsched_cleanup/schedlist.py`), and a dedicated CSV manifest (`id, old_operator, new_operator` — no full-file backups, per spec). `sync_operator_field.py` wires this into the standard three-mode CLI, reusing `rptsched_cleanup.quarantine.make_run_dir` for the timestamped run subfolder but not the move-based manifest (different shape).

**Tech Stack:** Python 3.6.8, standard library only (`argparse`, `csv`, `pathlib`, `os`, `shutil`, `tempfile`, `unittest`).

## Global Constraints

- Python 3.6.8, stdlib only — no third-party packages, no dataclasses, no f-string `=` debugging, no walrus operator.
- `--data-dir` and `--quarantine-dir` are always required CLI args, never hardcoded.
- Dry-run is the default mode (no flag); `--execute` and `--restore RUN_DIR` are mutually exclusive.
- Quarantine/manifest writes never delete or overwrite existing runs; `.set` files are rewritten in place via write-temp-file + atomic rename (`os.replace`), never a direct in-place edit.
- Comparison of operator vs. owner is exact string match, case-sensitive (no normalization).
- Orphans (no `schedlist` line), the inactivity rule, the ACQ exclusion, and SIRSI-as-owner are all explicitly **not** special-cased by this script — see `docs/superpowers/specs/2026-07-24-sync-operator-field-design.md`.
- `manifest.csv` is never deleted, during or after restore.

---

### Task 1: Mismatch detection

**Files:**
- Create: `rptsched_cleanup/operators.py`
- Test: `tests/test_operators.py`

**Interfaces:**
- Consumes: `tests/fixtures.py::make_data_dir(base_dir, schedlist_lines, extra_files)` (existing helper — writes a `schedlist` file plus placeholder files).
- Produces: `OperatorMismatch` namedtuple (`id, old_operator, new_operator`), `SkippedId` namedtuple (`id, reason`), `find_operator_mismatches(data_dir) -> (dict[str, OperatorMismatch], list[SkippedId])`. Later tasks in this module rely on these exact names.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_operators.py
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rptsched_cleanup.operators import find_operator_mismatches, OperatorMismatch, SkippedId
from tests.fixtures import make_data_dir


def _schedlist_line(template_id, owner):
    return "{}|noverdue|Some Template|n|200207021051|202001010000|{}||||||0|3||0|$<library_notice:c>|ENGLISH|".format(
        template_id, owner
    )


def _write_set_file(data_dir, template_id, operator_value, middle_field=""):
    (data_dir / "{}.set".format(template_id)).write_text(
        "# Copyright (c) 1992 - 2000, Sirsi Corporation.\n"
        "desc|0||$(14837)|\n"
        "operator|0|{}|{}|\n"
        "title|0||-t$(14836)|\n".format(middle_field, operator_value)
    )


class TestFindOperatorMismatches(unittest.TestCase):
    def test_detects_mismatch(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "REALOWNER")], [])
            _write_set_file(data_dir, "abcd", "STALEOWNER")

            mismatches, skipped = find_operator_mismatches(data_dir)

            self.assertEqual(skipped, [])
            self.assertEqual(
                mismatches,
                {"abcd": OperatorMismatch(id="abcd", old_operator="STALEOWNER", new_operator="REALOWNER")},
            )

    def test_no_mismatch_when_operator_matches_owner(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "SAMEOWNER")], [])
            _write_set_file(data_dir, "abcd", "SAMEOWNER")

            mismatches, skipped = find_operator_mismatches(data_dir)

            self.assertEqual(mismatches, {})
            self.assertEqual(skipped, [])

    def test_comparison_is_case_sensitive(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "WRIGCIRCMGR")], [])
            _write_set_file(data_dir, "abcd", "wrigcircmgr")

            mismatches, skipped = find_operator_mismatches(data_dir)

            self.assertEqual(
                mismatches,
                {"abcd": OperatorMismatch(id="abcd", old_operator="wrigcircmgr", new_operator="WRIGCIRCMGR")},
            )

    def test_middle_field_is_not_compared_or_touched_by_detection(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("jiqi", "SIRSI")], [])
            _write_set_file(data_dir, "jiqi", "SIRSI", middle_field="SIRSI")

            mismatches, skipped = find_operator_mismatches(data_dir)

            self.assertEqual(mismatches, {})

    def test_skips_id_with_no_matching_set_file(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "REALOWNER")], [])
            # no abcd.set written at all

            mismatches, skipped = find_operator_mismatches(data_dir)

            self.assertEqual(mismatches, {})
            self.assertEqual(skipped, [SkippedId(id="abcd", reason="missing .set file")])

    def test_skips_id_with_no_operator_line(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [_schedlist_line("abcd", "REALOWNER")], [])
            (data_dir / "abcd.set").write_text("desc|0||$(14837)|\ntitle|0||-t$(14836)|\n")

            mismatches, skipped = find_operator_mismatches(data_dir)

            self.assertEqual(mismatches, {})
            self.assertEqual(skipped, [SkippedId(id="abcd", reason="missing operator line")])

    def test_multiple_ids_mixed_results(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(
                tmp,
                [
                    _schedlist_line("aaaa", "OWNERA"),
                    _schedlist_line("bbbb", "OWNERB"),
                ],
                [],
            )
            _write_set_file(data_dir, "aaaa", "OWNERA")  # matches
            _write_set_file(data_dir, "bbbb", "STALE")   # mismatch

            mismatches, skipped = find_operator_mismatches(data_dir)

            self.assertEqual(set(mismatches.keys()), {"bbbb"})
            self.assertEqual(skipped, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_operators.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'rptsched_cleanup.operators'`)

- [ ] **Step 3: Implement `find_operator_mismatches`**

```python
# rptsched_cleanup/operators.py
from collections import namedtuple
from pathlib import Path

OperatorMismatch = namedtuple("OperatorMismatch", ["id", "old_operator", "new_operator"])
SkippedId = namedtuple("SkippedId", ["id", "reason"])


def _extract_operator(set_path):
    with set_path.open() as f:
        for line in f:
            if line.startswith("operator|"):
                fields = line.rstrip("\n").split("|")
                return fields[-2]
    return None


def find_operator_mismatches(data_dir):
    data_dir = Path(data_dir)
    owners = {}
    with (data_dir / "schedlist").open() as f:
        for line in f:
            raw_line = line.rstrip("\n")
            if not raw_line.strip():
                continue
            fields = raw_line.split("|")
            owners[fields[0]] = fields[6]

    mismatches = {}
    skipped = []
    for template_id in sorted(owners):
        owner = owners[template_id]
        set_path = data_dir / "{}.set".format(template_id)
        if not set_path.is_file():
            skipped.append(SkippedId(template_id, "missing .set file"))
            continue

        operator = _extract_operator(set_path)
        if operator is None:
            skipped.append(SkippedId(template_id, "missing operator line"))
            continue

        if operator != owner:
            mismatches[template_id] = OperatorMismatch(template_id, operator, owner)

    return mismatches, skipped
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_operators.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add rptsched_cleanup/operators.py tests/test_operators.py
git commit -m "Add operator/owner mismatch detection for sync_operator_field"
```

---

### Task 2: Single-line `.set` rewrite mechanics

**Files:**
- Modify: `rptsched_cleanup/operators.py`
- Test: `tests/test_operators.py`

**Interfaces:**
- Consumes: nothing new from Task 1's public surface besides the `.set` file layout already exercised by `_write_set_file` in tests.
- Produces: `read_operator(data_dir, template_id) -> str or None`, `rewrite_operator(data_dir, template_id, new_value) -> None`, `MissingOperatorLineError` (raised by `rewrite_operator` if the `.set` file has no `operator|` line). Task 4 (CLI restore) calls `read_operator` and `rewrite_operator` directly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_operators.py`:

```python
from rptsched_cleanup.operators import read_operator, rewrite_operator, MissingOperatorLineError


class TestReadOperator(unittest.TestCase):
    def test_reads_current_operator_value(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _write_set_file(data_dir, "abcd", "SOMEOWNER")

            self.assertEqual(read_operator(data_dir, "abcd"), "SOMEOWNER")

    def test_returns_none_for_missing_set_file(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)

            self.assertIsNone(read_operator(data_dir, "abcd"))


class TestRewriteOperator(unittest.TestCase):
    def test_rewrites_only_the_operator_value_field(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _write_set_file(data_dir, "abcd", "OLDVALUE", middle_field="SIRSI")

            rewrite_operator(data_dir, "abcd", "NEWVALUE")

            content = (data_dir / "abcd.set").read_text()
            self.assertIn("operator|0|SIRSI|NEWVALUE|", content)
            self.assertNotIn("OLDVALUE", content)
            # other lines untouched
            self.assertIn("desc|0||$(14837)|", content)
            self.assertIn("title|0||-t$(14836)|", content)

    def test_rewrite_is_atomic_no_tmp_file_left_behind(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            _write_set_file(data_dir, "abcd", "OLDVALUE")

            rewrite_operator(data_dir, "abcd", "NEWVALUE")

            remaining = list(data_dir.iterdir())
            self.assertEqual([p.name for p in remaining], ["abcd.set"])

    def test_raises_when_no_operator_line_present(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "abcd.set").write_text("desc|0||$(14837)|\n")

            with self.assertRaises(MissingOperatorLineError):
                rewrite_operator(data_dir, "abcd", "NEWVALUE")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_operators.py -v`
Expected: FAIL (`ImportError: cannot import name 'read_operator'`)

- [ ] **Step 3: Implement rewrite mechanics**

Add to `rptsched_cleanup/operators.py`:

```python
import os
import shutil
import tempfile


class MissingOperatorLineError(RuntimeError):
    pass


def read_operator(data_dir, template_id):
    set_path = Path(data_dir) / "{}.set".format(template_id)
    if not set_path.is_file():
        return None
    return _extract_operator(set_path)


def _atomic_write(set_path, lines):
    fd, tmp_path = tempfile.mkstemp(dir=str(set_path.parent), prefix=".{}.".format(set_path.name), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            for line in lines:
                f.write(line + "\n")
        shutil.copystat(str(set_path), tmp_path)
        os.replace(tmp_path, str(set_path))
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def rewrite_operator(data_dir, template_id, new_value):
    set_path = Path(data_dir) / "{}.set".format(template_id)

    lines = []
    found = False
    with set_path.open() as f:
        for line in f:
            raw_line = line.rstrip("\n")
            if raw_line.startswith("operator|"):
                fields = raw_line.split("|")
                fields[-2] = new_value
                lines.append("|".join(fields))
                found = True
            else:
                lines.append(raw_line)

    if not found:
        raise MissingOperatorLineError("No operator line found in {}".format(set_path))

    _atomic_write(set_path, lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_operators.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add rptsched_cleanup/operators.py tests/test_operators.py
git commit -m "Add atomic single-line rewrite for .set operator field"
```

---

### Task 3: Manifest I/O and batch apply

**Files:**
- Modify: `rptsched_cleanup/operators.py`
- Test: `tests/test_operators.py`

**Interfaces:**
- Consumes: `OperatorMismatch` (Task 1), `rewrite_operator` (Task 2), `rptsched_cleanup.quarantine.make_run_dir(quarantine_dir, prefix, timestamp) -> Path` (existing, reused as-is).
- Produces: `MANIFEST_FIELDS = ["id", "old_operator", "new_operator"]`, `write_operator_manifest(run_dir, rows) -> Path`, `read_operator_manifest(run_dir) -> list[dict]`, `OperatorRewriteError`, `apply_mismatches(data_dir, run_dir, mismatches) -> list[dict]`. Task 4 (CLI) calls `apply_mismatches` for `--execute` and `read_operator_manifest` for `--restore`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_operators.py`:

```python
from rptsched_cleanup.operators import (
    write_operator_manifest,
    read_operator_manifest,
    apply_mismatches,
    OperatorRewriteError,
    MANIFEST_FIELDS,
)
from rptsched_cleanup.quarantine import make_run_dir
from unittest.mock import patch


class TestManifestRoundTrip(unittest.TestCase):
    def test_write_then_read_round_trips_rows(self):
        with TemporaryDirectory() as tmp:
            run_dir = make_run_dir(Path(tmp) / "quarantine", "operators", "20260724_090000")
            rows = [{"id": "abcd", "old_operator": "OLD", "new_operator": "NEW"}]

            manifest_path = write_operator_manifest(run_dir, rows)

            self.assertEqual(manifest_path, run_dir / "manifest.csv")
            self.assertEqual(read_operator_manifest(run_dir), rows)

    def test_manifest_fields_order(self):
        self.assertEqual(MANIFEST_FIELDS, ["id", "old_operator", "new_operator"])


class TestApplyMismatches(unittest.TestCase):
    def test_rewrites_all_and_writes_manifest(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            _write_set_file(data_dir, "aaaa", "OLDA")
            _write_set_file(data_dir, "bbbb", "OLDB")
            run_dir = make_run_dir(Path(tmp) / "quarantine", "operators", "20260724_090000")

            mismatches = {
                "aaaa": OperatorMismatch("aaaa", "OLDA", "NEWA"),
                "bbbb": OperatorMismatch("bbbb", "OLDB", "NEWB"),
            }

            rows = apply_mismatches(data_dir, run_dir, mismatches)

            self.assertEqual(read_operator(data_dir, "aaaa"), "NEWA")
            self.assertEqual(read_operator(data_dir, "bbbb"), "NEWB")
            self.assertEqual(len(rows), 2)
            self.assertEqual(read_operator_manifest(run_dir), rows)

    def test_aborts_and_writes_partial_manifest_on_failure(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            _write_set_file(data_dir, "aaaa", "OLDA")
            _write_set_file(data_dir, "bbbb", "OLDB")
            run_dir = make_run_dir(Path(tmp) / "quarantine", "operators", "20260724_090000")

            mismatches = {
                "aaaa": OperatorMismatch("aaaa", "OLDA", "NEWA"),
                "bbbb": OperatorMismatch("bbbb", "OLDB", "NEWB"),
            }

            with patch("rptsched_cleanup.operators.os.replace", side_effect=OSError("simulated failure")):
                with self.assertRaises(OperatorRewriteError):
                    apply_mismatches(data_dir, run_dir, mismatches)

            # manifest reflects zero completed rewrites (aaaa sorts first and fails immediately)
            self.assertEqual(read_operator_manifest(run_dir), [])
            # original files untouched (atomic write failed before replace)
            self.assertEqual(read_operator(data_dir, "aaaa"), "OLDA")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_operators.py -v`
Expected: FAIL (`ImportError: cannot import name 'write_operator_manifest'`)

- [ ] **Step 3: Implement manifest I/O and batch apply**

Add to `rptsched_cleanup/operators.py`:

```python
import csv

MANIFEST_FIELDS = ["id", "old_operator", "new_operator"]
MANIFEST_FILENAME = "manifest.csv"


class OperatorRewriteError(RuntimeError):
    pass


def write_operator_manifest(run_dir, rows):
    manifest_path = Path(run_dir) / MANIFEST_FILENAME
    with manifest_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return manifest_path


def read_operator_manifest(run_dir):
    manifest_path = Path(run_dir) / MANIFEST_FILENAME
    with manifest_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def apply_mismatches(data_dir, run_dir, mismatches):
    rows = []
    try:
        for template_id in sorted(mismatches):
            m = mismatches[template_id]
            rewrite_operator(data_dir, template_id, m.new_operator)
            rows.append({"id": m.id, "old_operator": m.old_operator, "new_operator": m.new_operator})
    except OSError as err:
        write_operator_manifest(run_dir, rows)
        raise OperatorRewriteError(
            "Failed to rewrite operator field; {} id(s) corrected before the failure: {}".format(len(rows), err)
        ) from err

    write_operator_manifest(run_dir, rows)
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_operators.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add rptsched_cleanup/operators.py tests/test_operators.py
git commit -m "Add manifest I/O and batch-apply for operator field sync"
```

---

### Task 4: CLI — dry-run and `--execute` modes

**Files:**
- Create: `sync_operator_field.py`
- Test: `tests/test_sync_operator_field_cli.py`

**Interfaces:**
- Consumes: `find_operator_mismatches`, `apply_mismatches`, `OperatorRewriteError` (all from `rptsched_cleanup.operators`), `make_run_dir` (from `rptsched_cleanup.quarantine`).
- Produces: `main(argv=None) -> int`, matching the signature of `remove_stale_templates.main`. Task 5 extends this same file/function with the `--restore` branch.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sync_operator_field_cli.py
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import sync_operator_field
from rptsched_cleanup.operators import read_operator_manifest
from tests.fixtures import make_data_dir

MATCHING_LINE = "aaaa|noverdue|Matching Template|n|200207021051|202001010000|SAMEOWNER||||||0|3||0|$<library_notice:c>|ENGLISH|"
MISMATCH_LINE = "bbbb|noverdue|Mismatch Template|n|200207021051|202001010000|REALOWNER||||||0|3||0|$<library_notice:c>|ENGLISH|"


def _write_set_file(data_dir, template_id, operator_value):
    (data_dir / "{}.set".format(template_id)).write_text(
        "desc|0||$(14837)|\noperator|0||{}|\ntitle|0||-t$(14836)|\n".format(operator_value)
    )


class TestDryRun(unittest.TestCase):
    def test_dry_run_reports_mismatches_and_changes_nothing(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [MATCHING_LINE, MISMATCH_LINE], [])
            _write_set_file(data_dir, "aaaa", "SAMEOWNER")
            _write_set_file(data_dir, "bbbb", "STALEOWNER")
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("bbbb", out.getvalue())
            self.assertIn("STALEOWNER", out.getvalue())
            self.assertIn("REALOWNER", out.getvalue())
            self.assertNotIn("aaaa", out.getvalue())
            self.assertFalse(quarantine_dir.exists())
            self.assertIn("STALEOWNER", (data_dir / "bbbb.set").read_text())

    def test_dry_run_prints_warning_for_missing_set_file(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [MISMATCH_LINE], [])
            # bbbb.set intentionally not written
            quarantine_dir = Path(tmp) / "quarantine"

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("bbbb", err.getvalue())
            self.assertIn("missing .set file", err.getvalue())

    def test_missing_required_args_errors(self):
        with self.assertRaises(SystemExit):
            sync_operator_field.main([])


class TestExecute(unittest.TestCase):
    def test_execute_rewrites_operator_and_writes_manifest(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [MATCHING_LINE, MISMATCH_LINE], [])
            _write_set_file(data_dir, "aaaa", "SAMEOWNER")
            _write_set_file(data_dir, "bbbb", "STALEOWNER")
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("REALOWNER", (data_dir / "bbbb.set").read_text())
            self.assertIn("SAMEOWNER", (data_dir / "aaaa.set").read_text())

            run_dirs = list(quarantine_dir.glob("operators_*"))
            self.assertEqual(len(run_dirs), 1)
            rows = read_operator_manifest(run_dirs[0])
            self.assertEqual(rows, [{"id": "bbbb", "old_operator": "STALEOWNER", "new_operator": "REALOWNER"}])

    def test_execute_with_no_mismatches_touches_nothing(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [MATCHING_LINE], [])
            _write_set_file(data_dir, "aaaa", "SAMEOWNER")
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertFalse(quarantine_dir.exists())
            self.assertIn("no operator mismatch", out.getvalue().lower())

    def test_execute_aborts_and_reports_error_on_rewrite_failure(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [MISMATCH_LINE], [])
            _write_set_file(data_dir, "bbbb", "STALEOWNER")
            quarantine_dir = Path(tmp) / "quarantine"

            with patch("rptsched_cleanup.operators.os.replace", side_effect=OSError("simulated failure")):
                err = io.StringIO()
                with redirect_stdout(io.StringIO()), redirect_stderr(err):
                    exit_code = sync_operator_field.main([
                        "--data-dir", str(data_dir),
                        "--quarantine-dir", str(quarantine_dir),
                        "--execute",
                    ])

            self.assertEqual(exit_code, 1)
            self.assertIn("simulated failure", err.getvalue())
            self.assertIn("STALEOWNER", (data_dir / "bbbb.set").read_text())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sync_operator_field_cli.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'sync_operator_field'`)

- [ ] **Step 3: Implement the CLI (dry-run and `--execute` only for now)**

```python
#!/usr/bin/env python3
import argparse
import sys
from datetime import datetime
from pathlib import Path

from rptsched_cleanup.operators import find_operator_mismatches, apply_mismatches, OperatorRewriteError
from rptsched_cleanup.quarantine import make_run_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync .set operator field to match schedlist owner in a Symphony Rptsched directory."
    )
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--quarantine-dir", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--restore", metavar="RUN_DIR", type=Path)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    mismatches, skipped = find_operator_mismatches(args.data_dir)
    for skip in skipped:
        print("WARNING: {} skipped ({})".format(skip.id, skip.reason), file=sys.stderr)

    if not args.execute:
        print("DRY RUN: {} operator mismatch(es) found".format(len(mismatches)))
        for template_id in sorted(mismatches):
            m = mismatches[template_id]
            print("  {}: {} -> {}".format(m.id, m.old_operator, m.new_operator))
        return 0

    if not mismatches:
        print("No operator mismatches found; nothing to do.")
        return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = make_run_dir(args.quarantine_dir, "operators", timestamp)

    try:
        rows = apply_mismatches(args.data_dir, run_dir, mismatches)
    except OperatorRewriteError as err:
        print(str(err), file=sys.stderr)
        return 1

    print("Corrected {} operator value(s) in {}".format(len(rows), run_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sync_operator_field_cli.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add sync_operator_field.py tests/test_sync_operator_field_cli.py
git commit -m "Add sync_operator_field CLI: dry-run and --execute modes"
```

---

### Task 5: CLI — `--restore` mode

**Files:**
- Modify: `sync_operator_field.py`
- Test: `tests/test_sync_operator_field_cli.py`

**Interfaces:**
- Consumes: `read_operator`, `rewrite_operator`, `read_operator_manifest` (all from `rptsched_cleanup.operators`, Tasks 2–3).
- Produces: extends `main` to handle `args.restore`; no new public names.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sync_operator_field_cli.py`:

```python
from rptsched_cleanup.operators import read_operator


class TestRestore(unittest.TestCase):
    def test_restore_reverts_corrected_operator(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [MISMATCH_LINE], [])
            _write_set_file(data_dir, "bbbb", "STALEOWNER")
            quarantine_dir = Path(tmp) / "quarantine"

            with redirect_stdout(io.StringIO()):
                sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])
            run_dir = list(quarantine_dir.glob("operators_*"))[0]

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertEqual(read_operator(data_dir, "bbbb"), "STALEOWNER")
            self.assertIn("restored 1", out.getvalue().lower())

    def test_second_restore_is_idempotent(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [MISMATCH_LINE], [])
            _write_set_file(data_dir, "bbbb", "STALEOWNER")
            quarantine_dir = Path(tmp) / "quarantine"

            with redirect_stdout(io.StringIO()):
                sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])
            run_dir = list(quarantine_dir.glob("operators_*"))[0]

            with redirect_stdout(io.StringIO()):
                sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("restored 0", out.getvalue().lower())
            self.assertIn("skipped 1", out.getvalue().lower())
            self.assertEqual(read_operator(data_dir, "bbbb"), "STALEOWNER")

    def test_restore_aborts_on_unexpected_current_value(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [MISMATCH_LINE], [])
            _write_set_file(data_dir, "bbbb", "STALEOWNER")
            quarantine_dir = Path(tmp) / "quarantine"

            with redirect_stdout(io.StringIO()):
                sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])
            run_dir = list(quarantine_dir.glob("operators_*"))[0]

            # something else changed the operator value since the execute run
            from rptsched_cleanup.operators import rewrite_operator
            rewrite_operator(data_dir, "bbbb", "SOMETHINGELSE")

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = sync_operator_field.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("bbbb", err.getvalue())
            self.assertEqual(read_operator(data_dir, "bbbb"), "SOMETHINGELSE")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sync_operator_field_cli.py -v`
Expected: FAIL (`--restore` currently unhandled; `argparse` accepts the flag but `main` never reads `args.restore`, so these tests fail on the resulting assertions, e.g. `read_operator` still returning the corrected value)

- [ ] **Step 3: Implement `--restore`**

Modify `sync_operator_field.py` — add the import and insert the restore branch at the top of `main`, before mismatch detection runs:

```python
from rptsched_cleanup.operators import (
    find_operator_mismatches,
    apply_mismatches,
    read_operator,
    rewrite_operator,
    read_operator_manifest,
    OperatorRewriteError,
)
```

```python
def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.restore:
        rows = read_operator_manifest(args.restore)
        restored = 0
        skipped = 0
        for row in rows:
            template_id = row["id"]
            old_operator = row["old_operator"]
            new_operator = row["new_operator"]
            current = read_operator(args.data_dir, template_id)

            if current == old_operator:
                skipped += 1
                continue
            if current == new_operator:
                rewrite_operator(args.data_dir, template_id, old_operator)
                restored += 1
                continue

            print(
                "Cannot restore {}: current operator {!r} matches neither old ({!r}) nor new ({!r})".format(
                    template_id, current, old_operator, new_operator
                ),
                file=sys.stderr,
            )
            return 1

        print("Restored {} operator value(s), skipped {} already-restored".format(restored, skipped))
        return 0

    mismatches, skipped = find_operator_mismatches(args.data_dir)
    # ... rest unchanged from Task 4
```

(Keep the rest of `main` from Task 4 as-is below this new branch.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sync_operator_field_cli.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add sync_operator_field.py tests/test_sync_operator_field_cli.py
git commit -m "Add --restore mode to sync_operator_field CLI"
```

---

### Task 6: Integration test against local sample data

**Files:**
- Test: `tests/test_sync_operator_field_integration.py`

**Interfaces:**
- Consumes: `sync_operator_field.main` (Tasks 4–5), `rptsched_cleanup.operators.find_operator_mismatches` (Task 1), local `rptsched/` sample data directory (gitignored, may not be present — skip if absent, matching `test_remove_stale_templates_integration.py`).
- Produces: nothing consumed elsewhere; this is the final verification task.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sync_operator_field_integration.py
import io
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import sync_operator_field
from rptsched_cleanup.operators import find_operator_mismatches

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
```

- [ ] **Step 2: Run test to verify it fails or is skipped correctly**

Run: `python -m pytest tests/test_sync_operator_field_integration.py -v`
Expected: PASS immediately if `rptsched/` is present (module and functions already exist from Tasks 1–5) — this task's real value is running it against real sample data, not TDD red/green. If `rptsched/` is absent, both tests report `SKIPPED`, which is the correct outcome.

- [ ] **Step 3: No implementation needed**

Tasks 1–5 already provide everything this test exercises. If the test fails against real sample data, treat it as a bug found in Tasks 1–5 (fix there, re-run) rather than adding new code here.

- [ ] **Step 4: Run full test suite to confirm no regressions**

Run: `python -m pytest tests/ -v`
Expected: PASS (all tests, including pre-existing ones for orphans/stale-templates/quarantine/schedlist)

- [ ] **Step 5: Commit**

```bash
git add tests/test_sync_operator_field_integration.py
git commit -m "Add sync_operator_field integration test against local rptsched sample data"
```
