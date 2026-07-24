# remove_stale_templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `remove_stale_templates.py`, a CLI script that finds inactive manual saved templates in a Symphony `Rptsched` data directory, quarantines their files, and removes their line from `schedlist` — with a `--restore` mode that reverses a run.

**Architecture:** Two new small modules under `rptsched_cleanup/`: `templates.py` (candidate selection — parses `schedlist`, applies the manual/inactive/non-ACQ rule, groups each candidate's files on disk) and `schedlist.py` (generic `schedlist`-rewrite mechanics — remove lines / re-insert lines, both via write-temp-file + atomic-rename). A new `remove_stale_templates.py` CLI at the repo root wires these together with the existing `rptsched_cleanup/quarantine.py` module (`make_run_dir`, `move_groups_to_quarantine`, `restore_run` — unchanged, reused as-is) to implement dry-run / `--execute` / `--restore`. This mirrors the existing `remove_orphans.py` structure exactly.

**Tech Stack:** Python 3.6.8, standard library only (`argparse`, `re`, `csv` via existing `quarantine.py`, `datetime`, `tempfile` + `os.replace`, `unittest`).

## Global Constraints

- Python 3.6.8, stdlib only — no dataclasses, no f-string `=`, no walrus operator.
- `--data-dir` and `--quarantine-dir` are always explicit CLI args, never hardcoded.
- Dry-run is the default mode; nothing is written or moved unless `--execute` is passed.
- Quarantine is always a move, never a delete.
- `--restore` is idempotent and resumable; `manifest.csv` and `removed_schedlist_lines.txt` are never deleted.
- `schedlist` is only ever rewritten via write-temp-file-in-same-dir + `os.replace` (atomic), never edited in place.
- This script must not invoke `remove_orphans`' detection logic or otherwise share candidate-detection logic across scripts.
- Full behavioral spec: `docs/superpowers/specs/2026-07-24-remove-stale-templates-design.md`. Domain background (schedlist format, inactivity rule, ACQ exclusion): `rptsched-domain-reference.md`.

---

## Task 1: `schedlist` rewrite mechanics

**Files:**
- Create: `rptsched_cleanup/schedlist.py`
- Test: `tests/test_schedlist.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `remove_lines(data_dir, ids_to_remove) -> list[str]` — rewrites `<data_dir>/schedlist` atomically, excluding any line whose id is in `ids_to_remove`; returns the exact removed lines (verbatim, in original file order).
  - `insert_lines(data_dir, lines_to_insert) -> dict` — reads the current `<data_dir>/schedlist`, appends any line from `lines_to_insert` whose id isn't already present, re-sorts the whole file by id, and rewrites it atomically. Returns `{"inserted": int, "skipped": int}`.
  - Both used by Task 3's CLI.

- [ ] **Step 1: Write failing tests for `remove_lines`**

Create `tests/test_schedlist.py`:

```python
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rptsched_cleanup.schedlist import remove_lines, insert_lines
from tests.fixtures import make_data_dir


class TestRemoveLines(unittest.TestCase):
    def test_removes_matching_ids_and_returns_removed_lines_verbatim(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "abcd|noverdue|Keep Me|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
                "wxyz|noverdue|Remove Me|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, [])

            removed = remove_lines(data_dir, {"wxyz"})

            self.assertEqual(removed, [schedlist_lines[1]])
            remaining = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(remaining, [schedlist_lines[0]])

    def test_no_matching_ids_removes_nothing(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "abcd|noverdue|Keep Me|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, [])

            removed = remove_lines(data_dir, {"zzzz"})

            self.assertEqual(removed, [])
            remaining = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(remaining, schedlist_lines)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_schedlist.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rptsched_cleanup.schedlist'`

- [ ] **Step 3: Implement `remove_lines`**

Create `rptsched_cleanup/schedlist.py`:

```python
import os
import tempfile
from pathlib import Path

SCHEDLIST_FILENAME = "schedlist"


def _read_lines(schedlist_path: Path):
    with schedlist_path.open() as f:
        return [line.rstrip("\n") for line in f if line.strip()]


def _atomic_write(schedlist_path: Path, lines):
    fd, tmp_path = tempfile.mkstemp(dir=str(schedlist_path.parent), prefix=".schedlist.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            for line in lines:
                f.write(line + "\n")
        os.replace(tmp_path, str(schedlist_path))
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def remove_lines(data_dir, ids_to_remove) -> list:
    data_dir = Path(data_dir)
    schedlist_path = data_dir / SCHEDLIST_FILENAME
    ids_to_remove = set(ids_to_remove)

    remaining = []
    removed = []
    for raw_line in _read_lines(schedlist_path):
        template_id = raw_line.split("|")[0]
        if template_id in ids_to_remove:
            removed.append(raw_line)
        else:
            remaining.append(raw_line)

    _atomic_write(schedlist_path, remaining)
    return removed
```

- [ ] **Step 4: Run tests to verify `remove_lines` tests pass**

Run: `python3 -m pytest tests/test_schedlist.py -v`
Expected: `TestRemoveLines` tests PASS (insert_lines tests not written yet).

- [ ] **Step 5: Write failing tests for `insert_lines`**

Append to `tests/test_schedlist.py`:

```python
class TestInsertLines(unittest.TestCase):
    def test_inserts_missing_lines_and_sorts_by_id(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "aaaa|noverdue|First|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
                "zzzz|noverdue|Last|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, [])
            to_insert = [
                "mmmm|noverdue|Middle|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]

            result = insert_lines(data_dir, to_insert)

            self.assertEqual(result, {"inserted": 1, "skipped": 0})
            lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(lines, [schedlist_lines[0], to_insert[0], schedlist_lines[1]])

    def test_skips_ids_already_present(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "aaaa|noverdue|First|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, [])
            # Same id as an existing line, different content — must not duplicate.
            to_insert = [
                "aaaa|noverdue|Different Content Now|n|200207021051|202001010000|OTHERMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]

            result = insert_lines(data_dir, to_insert)

            self.assertEqual(result, {"inserted": 0, "skipped": 1})
            lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(lines, schedlist_lines)

    def test_second_insert_of_same_lines_is_idempotent(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [], [])
            to_insert = [
                "aaaa|noverdue|First|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]

            insert_lines(data_dir, to_insert)
            result = insert_lines(data_dir, to_insert)

            self.assertEqual(result, {"inserted": 0, "skipped": 1})
            lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(lines, to_insert)
```

- [ ] **Step 6: Run tests to verify the new tests fail**

Run: `python3 -m pytest tests/test_schedlist.py -v`
Expected: `TestInsertLines` tests FAIL — `ImportError: cannot import name 'insert_lines'`

- [ ] **Step 7: Implement `insert_lines`**

Append to `rptsched_cleanup/schedlist.py`:

```python
def insert_lines(data_dir, lines_to_insert) -> dict:
    data_dir = Path(data_dir)
    schedlist_path = data_dir / SCHEDLIST_FILENAME

    current_lines = _read_lines(schedlist_path)
    current_ids = {line.split("|")[0] for line in current_lines}

    inserted = 0
    skipped = 0
    for raw_line in lines_to_insert:
        template_id = raw_line.split("|")[0]
        if template_id in current_ids:
            skipped += 1
            continue
        current_lines.append(raw_line)
        current_ids.add(template_id)
        inserted += 1

    current_lines.sort(key=lambda line: line.split("|")[0])
    _atomic_write(schedlist_path, current_lines)
    return {"inserted": inserted, "skipped": skipped}
```

- [ ] **Step 8: Run all tests to verify they pass**

Run: `python3 -m pytest tests/test_schedlist.py -v`
Expected: All PASS.

- [ ] **Step 9: Commit**

```bash
git add rptsched_cleanup/schedlist.py tests/test_schedlist.py
git commit -m "Add schedlist rewrite mechanics (remove_lines, insert_lines)"
```

---

## Task 2: Stale-template candidate detection

**Files:**
- Create: `rptsched_cleanup/templates.py`
- Test: `tests/test_templates.py`

**Interfaces:**
- Consumes: nothing from other tasks (independent of Task 1).
- Produces:
  - `TemplateCandidate` — namedtuple with fields `id, raw_line, description, owner, frequency_flag, created, last_run, filenames` (`filenames` is a sorted `list[str]`).
  - `find_stale_template_candidates(data_dir, years=3, today=None) -> dict[str, TemplateCandidate]` — keyed by 4-char id. `today` defaults to `datetime.now()`; exposed as a parameter so tests can pin a reference date. Used by Task 3's CLI.

- [ ] **Step 1: Write failing tests for candidate selection**

Create `tests/test_templates.py`:

```python
import unittest
from datetime import datetime
from tempfile import TemporaryDirectory

from rptsched_cleanup.templates import find_stale_template_candidates
from tests.fixtures import make_data_dir

TODAY = datetime(2026, 7, 24)


def _line(template_id, frequency_flag="n", created="200207021051", last_run="200507270844", owner="SOMEMGR", description="Some Template"):
    return "{}|noverdue|{}|{}|{}|{}|{}||||||0|3||0|$<library_notice:c>|ENGLISH|".format(
        template_id, description, frequency_flag, created, last_run, owner
    )


class TestFindStaleTemplateCandidates(unittest.TestCase):
    def test_selects_manual_template_inactive_by_last_run(self):
        with TemporaryDirectory() as tmp:
            # last_run 2020 -> 6+ years before 2026-07-24, well past the 3yr default
            lines = [_line("abcd", last_run="202001010000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set", "abcd.selans"])

            candidates = find_stale_template_candidates(data_dir, years=3, today=TODAY)

            self.assertEqual(set(candidates.keys()), {"abcd"})
            candidate = candidates["abcd"]
            self.assertEqual(candidate.filenames, ["abcd.selans", "abcd.set"])
            self.assertEqual(candidate.frequency_flag, "n")

    def test_falls_back_to_created_when_never_run(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", created="202001010000", last_run="0000000000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(data_dir, years=3, today=TODAY)

            self.assertEqual(set(candidates.keys()), {"abcd"})

    def test_excludes_recurring_frequency_flag(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", frequency_flag="w1", last_run="202001010000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(data_dir, years=3, today=TODAY)

            self.assertEqual(candidates, {})

    def test_excludes_acq_owner_case_insensitive(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", owner="acqMGR", last_run="202001010000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(data_dir, years=3, today=TODAY)

            self.assertEqual(candidates, {})

    def test_excludes_recently_active_template(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", last_run="202601010000")]  # Jan 2026, well within 3yr of 2026-07-24
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(data_dir, years=3, today=TODAY)

            self.assertEqual(candidates, {})

    def test_custom_years_threshold(self):
        with TemporaryDirectory() as tmp:
            # last_run Jan 2025 -> ~1.5 years before 2026-07-24: stale at years=1, not at years=3
            lines = [_line("abcd", last_run="202501010000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            self.assertEqual(find_stale_template_candidates(data_dir, years=3, today=TODAY), {})
            self.assertEqual(
                set(find_stale_template_candidates(data_dir, years=1, today=TODAY).keys()),
                {"abcd"},
            )

    def test_candidate_with_no_files_on_disk_has_empty_filenames(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", last_run="202001010000")]
            data_dir = make_data_dir(tmp, lines, [])

            candidates = find_stale_template_candidates(data_dir, years=3, today=TODAY)

            self.assertEqual(candidates["abcd"].filenames, [])

    def test_defaults_today_to_now(self):
        with TemporaryDirectory() as tmp:
            lines = [_line("abcd", last_run="202001010000")]
            data_dir = make_data_dir(tmp, lines, ["abcd.set"])

            candidates = find_stale_template_candidates(data_dir)  # no today= override

            self.assertEqual(set(candidates.keys()), {"abcd"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_templates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rptsched_cleanup.templates'`

- [ ] **Step 3: Implement `templates.py`**

Create `rptsched_cleanup/templates.py`:

```python
import re
from collections import namedtuple
from datetime import datetime
from pathlib import Path

ID_PATTERN = re.compile(r'^([a-z0-9]{4})\.(.+)$')
NEVER_RUN = "0000000000"
DATETIME_FORMAT = "%Y%m%d%H%M"

TemplateCandidate = namedtuple(
    "TemplateCandidate",
    ["id", "raw_line", "description", "owner", "frequency_flag", "created", "last_run", "filenames"],
)


def _years_before(reference, years):
    try:
        return reference.replace(year=reference.year - years)
    except ValueError:
        # reference is Feb 29 and (year - years) isn't a leap year
        return reference.replace(month=2, day=28, year=reference.year - years)


def _is_stale(created, last_run, threshold):
    if last_run != NEVER_RUN:
        run_date = datetime.strptime(last_run, DATETIME_FORMAT)
    else:
        run_date = datetime.strptime(created, DATETIME_FORMAT)
    return run_date <= threshold


def _group_files_by_id(data_dir: Path):
    groups = {}
    for entry in data_dir.iterdir():
        if not entry.is_file():
            continue
        match = ID_PATTERN.match(entry.name)
        if not match:
            continue
        groups.setdefault(match.group(1), []).append(entry.name)
    return groups


def find_stale_template_candidates(data_dir, years=3, today=None):
    data_dir = Path(data_dir)
    if today is None:
        today = datetime.now()
    threshold = _years_before(today, years)

    file_groups = _group_files_by_id(data_dir)

    candidates = {}
    with (data_dir / "schedlist").open() as f:
        for line in f:
            raw_line = line.rstrip("\n")
            if not raw_line.strip():
                continue

            fields = raw_line.split("|")
            template_id, description, frequency_flag, created, last_run, owner = (
                fields[0], fields[2], fields[3], fields[4], fields[5], fields[6]
            )

            if frequency_flag != "n":
                continue
            if "acq" in owner.lower():
                continue
            if not _is_stale(created, last_run, threshold):
                continue

            candidates[template_id] = TemplateCandidate(
                id=template_id,
                raw_line=raw_line,
                description=description,
                owner=owner,
                frequency_flag=frequency_flag,
                created=created,
                last_run=last_run,
                filenames=sorted(file_groups.get(template_id, [])),
            )

    return candidates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_templates.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add rptsched_cleanup/templates.py tests/test_templates.py
git commit -m "Add stale saved-template candidate detection"
```

---

## Task 3: `remove_stale_templates.py` CLI

**Files:**
- Create: `remove_stale_templates.py`
- Test: `tests/test_remove_stale_templates_cli.py`

**Interfaces:**
- Consumes:
  - `find_stale_template_candidates(data_dir, years=3, today=None) -> dict[str, TemplateCandidate]` (Task 2), where `TemplateCandidate` has `.id, .raw_line, .description, .owner, .frequency_flag, .created, .last_run, .filenames`.
  - `remove_lines(data_dir, ids_to_remove) -> list[str]` and `insert_lines(data_dir, lines_to_insert) -> dict` (Task 1).
  - `make_run_dir(quarantine_dir, prefix, timestamp) -> Path`, `move_groups_to_quarantine(data_dir, run_dir, groups, moved_at) -> list[dict]`, `restore_run(run_dir) -> dict`, `QuarantineMoveError`, `QuarantineRestoreError` from existing `rptsched_cleanup/quarantine.py` (unmodified).
- Produces: `main(argv=None) -> int`, the CLI entry point, for the integration test in Task 4.

- [ ] **Step 1: Write failing tests for dry-run mode**

Create `tests/test_remove_stale_templates_cli.py`:

```python
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import remove_stale_templates
from rptsched_cleanup.quarantine import read_manifest
from tests.fixtures import make_data_dir

STALE_LINE = "wxyz|noverdue|Stale Template|n|200207021051|202001010000|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"
ACTIVE_LINE = "abcd|noverdue|Active Template|n|200207021051|202601010000|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"


class TestDryRun(unittest.TestCase):
    def test_dry_run_reports_candidates_and_changes_nothing(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("wxyz", out.getvalue())
            self.assertNotIn("abcd", out.getvalue())
            self.assertFalse(quarantine_dir.exists())
            self.assertTrue((data_dir / "wxyz.set").exists())
            schedlist_text = (data_dir / "schedlist").read_text()
            self.assertIn("wxyz", schedlist_text)
            self.assertIn("abcd", schedlist_text)

    def test_missing_required_args_errors(self):
        with self.assertRaises(SystemExit):
            remove_stale_templates.main([])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_remove_stale_templates_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'remove_stale_templates'`

- [ ] **Step 3: Implement the CLI skeleton and dry-run mode**

Create `remove_stale_templates.py`:

```python
#!/usr/bin/env python3
import argparse
import sys
from datetime import datetime
from pathlib import Path

from rptsched_cleanup.templates import find_stale_template_candidates
from rptsched_cleanup.schedlist import remove_lines, insert_lines
from rptsched_cleanup.quarantine import (
    QuarantineMoveError,
    QuarantineRestoreError,
    make_run_dir,
    move_groups_to_quarantine,
    restore_run,
)

REMOVED_LINES_FILENAME = "removed_schedlist_lines.txt"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove stale saved templates (manual, inactive) from a Symphony Rptsched directory."
    )
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--quarantine-dir", required=True, type=Path)
    parser.add_argument("--years", type=int, default=3)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--restore", metavar="RUN_DIR", type=Path)
    return parser


def _write_removed_lines(run_dir: Path, removed_lines) -> Path:
    path = Path(run_dir) / REMOVED_LINES_FILENAME
    with path.open("w") as f:
        for line in removed_lines:
            f.write(line + "\n")
    return path


def _read_removed_lines(run_dir: Path):
    path = Path(run_dir) / REMOVED_LINES_FILENAME
    with path.open() as f:
        return [line.rstrip("\n") for line in f if line.strip()]


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.restore:
        try:
            file_result = restore_run(args.restore)
        except QuarantineRestoreError as err:
            print(str(err), file=sys.stderr)
            return 1

        removed_lines = _read_removed_lines(args.restore)
        schedlist_result = insert_lines(args.data_dir, removed_lines)

        print("Restored {} file(s), skipped {} already-restored".format(
            file_result["restored"], file_result["skipped"]))
        print("Re-inserted {} schedlist line(s), skipped {} already present".format(
            schedlist_result["inserted"], schedlist_result["skipped"]))
        return 0

    candidates = find_stale_template_candidates(args.data_dir, years=args.years)
    total_files = sum(len(c.filenames) for c in candidates.values())

    if not args.execute:
        print("DRY RUN: {} stale template(s), {} file(s) would be moved".format(len(candidates), total_files))
        for template_id in sorted(candidates):
            c = candidates[template_id]
            print("  {}: {} | owner={} | freq={} | created={} | last_run={} | files={}".format(
                c.id, c.description, c.owner, c.frequency_flag, c.created, c.last_run,
                ", ".join(c.filenames)))
        return 0

    groups = {template_id: c.filenames for template_id, c in candidates.items()}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = make_run_dir(args.quarantine_dir, "templates", timestamp)
    try:
        move_groups_to_quarantine(args.data_dir, run_dir, groups, moved_at=timestamp)
    except QuarantineMoveError as err:
        print(str(err), file=sys.stderr)
        return 1

    removed_lines = [candidates[template_id].raw_line for template_id in sorted(candidates)]
    _write_removed_lines(run_dir, removed_lines)
    remove_lines(args.data_dir, set(candidates.keys()))

    print("Moved {} file(s) across {} stale template(s) into {}".format(
        total_files, len(candidates), run_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify dry-run tests pass**

Run: `python3 -m pytest tests/test_remove_stale_templates_cli.py -v`
Expected: `TestDryRun` tests PASS.

- [ ] **Step 5: Write failing tests for `--execute`**

Append to `tests/test_remove_stale_templates_cli.py`:

```python
class TestExecute(unittest.TestCase):
    def test_execute_moves_files_writes_manifest_and_rewrites_schedlist(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertFalse((data_dir / "wxyz.set").exists())
            self.assertFalse((data_dir / "wxyz.selans").exists())
            self.assertTrue((data_dir / "abcd.set").exists())

            schedlist_lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(schedlist_lines, [ACTIVE_LINE])

            run_dirs = list(quarantine_dir.glob("templates_*"))
            self.assertEqual(len(run_dirs), 1)
            run_dir = run_dirs[0]

            rows = read_manifest(run_dir)
            self.assertEqual(len(rows), 2)

            removed_text = (run_dir / "removed_schedlist_lines.txt").read_text().splitlines()
            self.assertEqual(removed_text, [STALE_LINE])

    def test_execute_with_no_candidates_touches_nothing(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [ACTIVE_LINE], ["abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            with redirect_stdout(io.StringIO()):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertTrue((data_dir / "abcd.set").exists())
            schedlist_lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(schedlist_lines, [ACTIVE_LINE])

    def test_execute_aborts_before_schedlist_rewrite_on_move_failure(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE], ["wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            with patch("rptsched_cleanup.quarantine.shutil.move", side_effect=OSError("simulated failure")):
                err = io.StringIO()
                with redirect_stdout(io.StringIO()), redirect_stderr(err):
                    exit_code = remove_stale_templates.main([
                        "--data-dir", str(data_dir),
                        "--quarantine-dir", str(quarantine_dir),
                        "--execute",
                    ])

            self.assertEqual(exit_code, 1)
            self.assertIn("wxyz.set", err.getvalue())
            # schedlist must be untouched — the failed move happens before any schedlist rewrite
            schedlist_lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(schedlist_lines, [STALE_LINE])
            self.assertTrue((data_dir / "wxyz.set").exists())

    def test_years_override_changes_candidate_set(self):
        with TemporaryDirectory() as tmp:
            # last_run ~1.5 years before "now" — not stale at years=3, stale at years=1
            recent_but_old_line = "mmmm|noverdue|Middling|n|200207021051|202501010000|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|"
            data_dir = make_data_dir(tmp, [recent_but_old_line], ["mmmm.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--years", "1",
                ])

            self.assertIn("mmmm", out.getvalue())
```

- [ ] **Step 6: Run tests to verify the new tests fail**

Run: `python3 -m pytest tests/test_remove_stale_templates_cli.py -v`
Expected: `TestExecute` tests FAIL (schedlist not yet filtered correctly / behavior not wired — actually implementation from Step 3 already covers this; if it fails, it indicates a bug in Step 3's code to fix now). If they unexpectedly pass already, proceed — that means Step 3's implementation already satisfies them, which is fine.

- [ ] **Step 7: Fix implementation if any `TestExecute` test failed**

Re-inspect `remove_stale_templates.py` against the failing assertion and adjust `main()` until all pass. (The reference implementation in Step 3 is expected to satisfy these as written.)

- [ ] **Step 8: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_remove_stale_templates_cli.py -v`
Expected: All PASS.

- [ ] **Step 9: Write failing tests for `--restore`**

Append to `tests/test_remove_stale_templates_cli.py`:

```python
class TestRestore(unittest.TestCase):
    def test_restore_moves_files_back_and_reinserts_schedlist_line(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE, ACTIVE_LINE], ["wxyz.set", "wxyz.selans", "abcd.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            with redirect_stdout(io.StringIO()):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            run_dir = list(quarantine_dir.glob("templates_*"))[0]

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertTrue((data_dir / "wxyz.set").is_file())
            self.assertTrue((data_dir / "wxyz.selans").is_file())
            self.assertIn("restored", out.getvalue().lower())
            self.assertIn("re-inserted", out.getvalue().lower())

            schedlist_lines = sorted((data_dir / "schedlist").read_text().splitlines())
            self.assertEqual(schedlist_lines, sorted([STALE_LINE, ACTIVE_LINE]))

    def test_second_restore_is_idempotent(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE], ["wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            with redirect_stdout(io.StringIO()):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])
            run_dir = list(quarantine_dir.glob("templates_*"))[0]

            with redirect_stdout(io.StringIO()):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("Restored 0 file(s), skipped 1", out.getvalue())
            self.assertIn("Re-inserted 0 schedlist line(s), skipped 1", out.getvalue())
            schedlist_lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(schedlist_lines, [STALE_LINE])  # not duplicated

    def test_restore_conflict_prints_error_exits_nonzero_and_skips_schedlist_phase(self):
        with TemporaryDirectory() as tmp:
            data_dir = make_data_dir(tmp, [STALE_LINE], ["wxyz.set"])
            quarantine_dir = Path(tmp) / "quarantine"

            with redirect_stdout(io.StringIO()):
                remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])
            run_dir = list(quarantine_dir.glob("templates_*"))[0]

            # Recreate a file at its original location so restore hits a conflict.
            (data_dir / "wxyz.set").write_text("conflicting content")

            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                exit_code = remove_stale_templates.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 1)
            self.assertIn("wxyz.set", err.getvalue())
            self.assertIn("already exists", err.getvalue())
            # Phase 2 (schedlist) must not have run since Phase 1 failed
            schedlist_lines = (data_dir / "schedlist").read_text().splitlines()
            self.assertEqual(schedlist_lines, [])
```

- [ ] **Step 10: Run tests to verify they fail appropriately**

Run: `python3 -m pytest tests/test_remove_stale_templates_cli.py -v`
Expected: `TestRestore` tests run against the Step 3 implementation. If any fail, they indicate a real bug (e.g. Phase 2 running when Phase 1 failed) — fix `main()`'s `--restore` branch until the try/except around `restore_run` correctly returns before touching `insert_lines`.

- [ ] **Step 11: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_remove_stale_templates_cli.py -v`
Expected: All PASS.

- [ ] **Step 12: Commit**

```bash
git add remove_stale_templates.py tests/test_remove_stale_templates_cli.py
git commit -m "Add remove_stale_templates CLI (dry-run, --execute, --restore)"
```

---

## Task 4: Integration test against local sample data

**Files:**
- Create: `tests/test_remove_stale_templates_integration.py`

**Interfaces:**
- Consumes: `remove_stale_templates.main` (Task 3), `find_stale_template_candidates` (Task 2). No new interfaces produced.

- [ ] **Step 1: Write the integration test**

Create `tests/test_remove_stale_templates_integration.py`:

```python
import io
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import remove_stale_templates
from rptsched_cleanup.templates import find_stale_template_candidates

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
```

- [ ] **Step 2: Run the integration test**

Run: `python3 -m pytest tests/test_remove_stale_templates_integration.py -v`
Expected: PASS if local `rptsched/` sample data is present; SKIPPED otherwise (matches `test_remove_orphans_integration.py`'s existing skip behavior).

- [ ] **Step 3: Run the full test suite**

Run: `python3 -m pytest -v`
Expected: All tests PASS (or SKIPPED for integration tests without local sample data), no regressions in existing `remove_orphans` tests.

- [ ] **Step 4: Commit**

```bash
git add tests/test_remove_stale_templates_integration.py
git commit -m "Add integration test for remove_stale_templates against local rptsched sample data"
```
