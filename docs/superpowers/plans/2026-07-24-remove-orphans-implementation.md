# remove_orphans Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `remove_orphans` script per `docs/superpowers/specs/2026-07-24-remove-orphans-design.md` — detect `<id>.*` file groups in the Rptsched data directory with no `schedlist` line, and move them to quarantine (dry-run by default, `--execute` to act, `--restore` to reverse).

**Architecture:** A small `rptsched_cleanup` package holds two modules: `quarantine.py` (the move/manifest/restore mechanics — shared with the future stale-templates script) and `orphans.py` (orphan detection only). `remove_orphans.py` at the repo root is a thin CLI that wires the two together. All logic is unit-tested against `tmp_path`-style fixtures; a final integration test runs the whole CLI against a throwaway copy of the real local `rptsched/` sample data to sanity-check the counts (227 ids, 40 orphans) match what's already been verified by hand.

**Tech Stack:** Python 3.6.8, standard library only (`argparse`, `csv`, `pathlib`, `shutil`, `re`, `datetime`, `unittest`, `unittest.mock`).

## Global Constraints

- Python 3.6.8, standard library only — no third-party packages (RHEL8 production server, no admin rights, `pip install` not dependable).
- No dataclasses (3.7+), no f-string `=` debugging or walrus operator (3.8+) — plain classes and regular f-strings only.
- `--data-dir` and `--quarantine-dir` are always required CLI arguments, never hardcoded — same script must run unmodified against a local test copy or production.
- Quarantine is always a **move**, never a delete.
- Default mode (no flag) is dry-run: console output only, nothing written or moved.
- `--execute` creates `quarantine-dir/orphans_<YYYYMMDD_HHMMSS>/`, moves every file in every orphan group into it flat, writes `manifest.csv` (columns: `id, filename, extension, source_path, dest_path, moved_at`), and **aborts immediately** on the first individual move failure — the manifest must still reflect exactly what succeeded before the abort.
- `--restore <run-subfolder>` is idempotent and resumable: skip any manifest row whose `dest_path` no longer exists (already restored), abort immediately on an individual failure. `manifest.csv` is never deleted, during or after restore.
- Files not matching `^[a-z0-9]{4}\.(.+)$` (e.g. `schedid`, `schedid.migr`, timestamped `schedlist.*` backups) are always ignored — out of scope, not reported.

---

## File Structure

```
rptsched_cleanup/
    __init__.py
    quarantine.py        # shared move/manifest/restore mechanics
    orphans.py            # orphan detection only
remove_orphans.py         # CLI entry point
tests/
    __init__.py
    fixtures.py            # shared test fixture helpers
    test_quarantine.py
    test_orphans.py
    test_remove_orphans_cli.py
```

---

### Task 1: Package skeleton + `make_run_dir`

**Files:**
- Create: `rptsched_cleanup/__init__.py` (empty)
- Create: `rptsched_cleanup/quarantine.py`
- Create: `tests/__init__.py` (empty)
- Test: `tests/test_quarantine.py`

**Interfaces:**
- Produces: `make_run_dir(quarantine_dir: Path, prefix: str, timestamp: str) -> Path` — creates `quarantine_dir` (and parents) if missing, creates `quarantine_dir/<prefix>_<timestamp>` (must not already exist — raises `FileExistsError` if it does, since that would mean two runs collided on the same timestamp), returns the new path.

- [ ] **Step 1: Write the failing test**

Create `tests/__init__.py` (empty file) and `rptsched_cleanup/__init__.py` (empty file).

Create `tests/test_quarantine.py`:

```python
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rptsched_cleanup.quarantine import make_run_dir


class TestMakeRunDir(unittest.TestCase):
    def test_creates_quarantine_dir_and_run_subfolder(self):
        with TemporaryDirectory() as tmp:
            quarantine_dir = Path(tmp) / "quarantine"
            run_dir = make_run_dir(quarantine_dir, "orphans", "20260724_090000")

            self.assertTrue(run_dir.is_dir())
            self.assertEqual(run_dir, quarantine_dir / "orphans_20260724_090000")

    def test_raises_if_run_dir_already_exists(self):
        with TemporaryDirectory() as tmp:
            quarantine_dir = Path(tmp) / "quarantine"
            make_run_dir(quarantine_dir, "orphans", "20260724_090000")

            with self.assertRaises(FileExistsError):
                make_run_dir(quarantine_dir, "orphans", "20260724_090000")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_quarantine -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'rptsched_cleanup.quarantine'` (module doesn't exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `rptsched_cleanup/quarantine.py`:

```python
from pathlib import Path


def make_run_dir(quarantine_dir: Path, prefix: str, timestamp: str) -> Path:
    quarantine_dir = Path(quarantine_dir)
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    run_dir = quarantine_dir / "{}_{}".format(prefix, timestamp)
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_quarantine -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add rptsched_cleanup/__init__.py rptsched_cleanup/quarantine.py tests/__init__.py tests/test_quarantine.py
git commit -m "Add make_run_dir for quarantine run subfolder creation"
```

---

### Task 2: `write_manifest` / `read_manifest`

**Files:**
- Modify: `rptsched_cleanup/quarantine.py`
- Test: `tests/test_quarantine.py`

**Interfaces:**
- Consumes: nothing new from Task 1.
- Produces:
  - `MANIFEST_FIELDS = ["id", "filename", "extension", "source_path", "dest_path", "moved_at"]`
  - `write_manifest(run_dir: Path, rows: List[dict]) -> Path` — writes `run_dir/manifest.csv` with `MANIFEST_FIELDS` as the header, one row per dict (each dict has exactly those keys, values as strings). Returns the manifest path.
  - `read_manifest(run_dir: Path) -> List[dict]` — reads `run_dir/manifest.csv`, returns a list of row dicts with the same keys.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_quarantine.py`:

```python
from rptsched_cleanup.quarantine import make_run_dir, write_manifest, read_manifest, MANIFEST_FIELDS


class TestManifestRoundTrip(unittest.TestCase):
    def test_write_then_read_round_trips_rows(self):
        with TemporaryDirectory() as tmp:
            run_dir = make_run_dir(Path(tmp) / "quarantine", "orphans", "20260724_090000")
            rows = [
                {
                    "id": "abcd",
                    "filename": "abcd.set",
                    "extension": "set",
                    "source_path": str(Path(tmp) / "data" / "abcd.set"),
                    "dest_path": str(run_dir / "abcd.set"),
                    "moved_at": "20260724_090000",
                }
            ]

            manifest_path = write_manifest(run_dir, rows)

            self.assertEqual(manifest_path, run_dir / "manifest.csv")
            self.assertTrue(manifest_path.is_file())

            read_rows = read_manifest(run_dir)
            self.assertEqual(read_rows, rows)

    def test_manifest_fields_order(self):
        self.assertEqual(
            MANIFEST_FIELDS,
            ["id", "filename", "extension", "source_path", "dest_path", "moved_at"],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_quarantine -v`
Expected: FAIL — `ImportError: cannot import name 'write_manifest'`

- [ ] **Step 3: Write minimal implementation**

Add to `rptsched_cleanup/quarantine.py`:

```python
import csv

MANIFEST_FIELDS = ["id", "filename", "extension", "source_path", "dest_path", "moved_at"]
MANIFEST_FILENAME = "manifest.csv"


def write_manifest(run_dir: Path, rows) -> Path:
    manifest_path = Path(run_dir) / MANIFEST_FILENAME
    with manifest_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return manifest_path


def read_manifest(run_dir: Path):
    manifest_path = Path(run_dir) / MANIFEST_FILENAME
    with manifest_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_quarantine -v`
Expected: PASS (4 tests total)

- [ ] **Step 5: Commit**

```bash
git add rptsched_cleanup/quarantine.py tests/test_quarantine.py
git commit -m "Add manifest.csv read/write to quarantine module"
```

---

### Task 3: `move_groups_to_quarantine` — success path

**Files:**
- Modify: `rptsched_cleanup/quarantine.py`
- Test: `tests/test_quarantine.py`

**Interfaces:**
- Consumes: `write_manifest` from Task 2.
- Produces: `move_groups_to_quarantine(data_dir: Path, run_dir: Path, groups: Dict[str, List[str]], moved_at: str) -> List[dict]` — for every `(id, [filenames])` in `groups` (processed in sorted-id order, filenames sorted within each group, for determinism), moves `data_dir/filename` to `run_dir/filename` via `shutil.move`. On full success, writes `manifest.csv` into `run_dir` via `write_manifest` and returns the list of row dicts written.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_quarantine.py`:

```python
from rptsched_cleanup.quarantine import move_groups_to_quarantine


class TestMoveGroupsSuccess(unittest.TestCase):
    def test_moves_all_files_and_writes_manifest(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            (data_dir / "abcd.set").write_text("set content")
            (data_dir / "abcd.user").write_text("user content")
            (data_dir / "efgh.set").write_text("other set content")

            run_dir = make_run_dir(Path(tmp) / "quarantine", "orphans", "20260724_090000")
            groups = {"abcd": ["abcd.set", "abcd.user"], "efgh": ["efgh.set"]}

            rows = move_groups_to_quarantine(data_dir, run_dir, groups, moved_at="20260724_090000")

            self.assertEqual(len(rows), 3)
            self.assertFalse((data_dir / "abcd.set").exists())
            self.assertFalse((data_dir / "abcd.user").exists())
            self.assertFalse((data_dir / "efgh.set").exists())
            self.assertTrue((run_dir / "abcd.set").is_file())
            self.assertTrue((run_dir / "abcd.user").is_file())
            self.assertTrue((run_dir / "efgh.set").is_file())
            self.assertTrue((run_dir / "manifest.csv").is_file())

            read_rows = read_manifest(run_dir)
            self.assertEqual(read_rows, rows)

            abcd_set_row = next(r for r in rows if r["filename"] == "abcd.set")
            self.assertEqual(abcd_set_row["id"], "abcd")
            self.assertEqual(abcd_set_row["extension"], "set")
            self.assertEqual(abcd_set_row["source_path"], str(data_dir / "abcd.set"))
            self.assertEqual(abcd_set_row["dest_path"], str(run_dir / "abcd.set"))
            self.assertEqual(abcd_set_row["moved_at"], "20260724_090000")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_quarantine -v`
Expected: FAIL — `ImportError: cannot import name 'move_groups_to_quarantine'`

- [ ] **Step 3: Write minimal implementation**

Add to `rptsched_cleanup/quarantine.py`:

```python
import shutil


def move_groups_to_quarantine(data_dir: Path, run_dir: Path, groups, moved_at: str):
    data_dir = Path(data_dir)
    run_dir = Path(run_dir)
    rows = []

    for file_id in sorted(groups):
        for filename in sorted(groups[file_id]):
            source_path = data_dir / filename
            dest_path = run_dir / filename
            shutil.move(str(source_path), str(dest_path))

            extension = filename.split(".", 1)[1] if "." in filename else ""
            rows.append({
                "id": file_id,
                "filename": filename,
                "extension": extension,
                "source_path": str(source_path),
                "dest_path": str(dest_path),
                "moved_at": moved_at,
            })

    write_manifest(run_dir, rows)
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_quarantine -v`
Expected: PASS (5 tests total)

- [ ] **Step 5: Commit**

```bash
git add rptsched_cleanup/quarantine.py tests/test_quarantine.py
git commit -m "Add move_groups_to_quarantine success path"
```

---

### Task 4: `move_groups_to_quarantine` — abort-on-failure path

**Files:**
- Modify: `rptsched_cleanup/quarantine.py`
- Test: `tests/test_quarantine.py`

**Interfaces:**
- Consumes: `move_groups_to_quarantine` from Task 3.
- Produces: `QuarantineMoveError(RuntimeError)` — raised when an individual file move fails. `move_groups_to_quarantine` must, on this failure, still call `write_manifest` with exactly the rows for files successfully moved before the failure, then raise `QuarantineMoveError` (chained from the original exception via `raise ... from err`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_quarantine.py`:

```python
from unittest.mock import patch
from rptsched_cleanup.quarantine import QuarantineMoveError


class TestMoveGroupsAbortOnFailure(unittest.TestCase):
    def test_aborts_and_writes_partial_manifest_on_move_failure(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            (data_dir / "abcd.set").write_text("set content")
            (data_dir / "efgh.set").write_text("other set content")

            run_dir = make_run_dir(Path(tmp) / "quarantine", "orphans", "20260724_090000")
            groups = {"abcd": ["abcd.set"], "efgh": ["efgh.set"]}

            real_move = shutil.move

            def fail_on_efgh(src, dst):
                if "efgh" in src:
                    raise OSError("simulated failure moving efgh.set")
                return real_move(src, dst)

            with patch("rptsched_cleanup.quarantine.shutil.move", side_effect=fail_on_efgh):
                with self.assertRaises(QuarantineMoveError):
                    move_groups_to_quarantine(data_dir, run_dir, groups, moved_at="20260724_090000")

            # abcd moved (sorts before efgh), efgh did not
            self.assertFalse((data_dir / "abcd.set").exists())
            self.assertTrue((run_dir / "abcd.set").is_file())
            self.assertTrue((data_dir / "efgh.set").exists())
            self.assertFalse((run_dir / "efgh.set").exists())

            # manifest reflects only the successful move
            rows = read_manifest(run_dir)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["filename"], "abcd.set")
```

Add `import shutil` at the top of `tests/test_quarantine.py` if not already present (it's needed for `real_move = shutil.move`).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_quarantine -v`
Expected: FAIL — `ImportError: cannot import name 'QuarantineMoveError'`

- [ ] **Step 3: Write minimal implementation**

Modify `move_groups_to_quarantine` in `rptsched_cleanup/quarantine.py`:

```python
class QuarantineMoveError(RuntimeError):
    pass


def move_groups_to_quarantine(data_dir: Path, run_dir: Path, groups, moved_at: str):
    data_dir = Path(data_dir)
    run_dir = Path(run_dir)
    rows = []

    try:
        for file_id in sorted(groups):
            for filename in sorted(groups[file_id]):
                source_path = data_dir / filename
                dest_path = run_dir / filename
                shutil.move(str(source_path), str(dest_path))

                extension = filename.split(".", 1)[1] if "." in filename else ""
                rows.append({
                    "id": file_id,
                    "filename": filename,
                    "extension": extension,
                    "source_path": str(source_path),
                    "dest_path": str(dest_path),
                    "moved_at": moved_at,
                })
    except OSError as err:
        write_manifest(run_dir, rows)
        raise QuarantineMoveError(
            "Failed to move a file to quarantine; {} file(s) moved before the failure: {}".format(len(rows), err)
        ) from err

    write_manifest(run_dir, rows)
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_quarantine -v`
Expected: PASS (6 tests total)

- [ ] **Step 5: Commit**

```bash
git add rptsched_cleanup/quarantine.py tests/test_quarantine.py
git commit -m "Abort move_groups_to_quarantine on failure, keeping partial manifest"
```

---

### Task 5: `restore_run`

**Files:**
- Modify: `rptsched_cleanup/quarantine.py`
- Test: `tests/test_quarantine.py`

**Interfaces:**
- Consumes: `read_manifest` from Task 2, `QuarantineMoveError` pattern from Task 4 (same style, new exception class).
- Produces:
  - `QuarantineRestoreError(RuntimeError)`
  - `restore_run(run_dir: Path) -> dict` — reads `manifest.csv` from `run_dir`. For each row (in file order): if `dest_path` no longer exists, skip it (already restored). Else if `source_path` already exists, raise `QuarantineRestoreError` immediately (conflict — refuse to silently overwrite something that now occupies that path). Else move `dest_path` back to `source_path`. On any `OSError` during the move, raise `QuarantineRestoreError` immediately, leaving remaining rows unmoved. Returns `{"restored": <int>, "skipped": <int>}` counting only what *this call* did.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_quarantine.py`:

```python
from rptsched_cleanup.quarantine import restore_run, QuarantineRestoreError


class TestRestoreRun(unittest.TestCase):
    def _setup_run(self, tmp):
        data_dir = Path(tmp) / "data"
        data_dir.mkdir()
        (data_dir / "abcd.set").write_text("set content")
        (data_dir / "efgh.set").write_text("other set content")

        run_dir = make_run_dir(Path(tmp) / "quarantine", "orphans", "20260724_090000")
        groups = {"abcd": ["abcd.set"], "efgh": ["efgh.set"]}
        move_groups_to_quarantine(data_dir, run_dir, groups, moved_at="20260724_090000")
        return data_dir, run_dir

    def test_restores_all_files(self):
        with TemporaryDirectory() as tmp:
            data_dir, run_dir = self._setup_run(tmp)

            result = restore_run(run_dir)

            self.assertEqual(result, {"restored": 2, "skipped": 0})
            self.assertTrue((data_dir / "abcd.set").is_file())
            self.assertTrue((data_dir / "efgh.set").is_file())
            self.assertFalse((run_dir / "abcd.set").exists())
            self.assertFalse((run_dir / "efgh.set").exists())
            # manifest is never deleted
            self.assertTrue((run_dir / "manifest.csv").is_file())

    def test_second_restore_is_idempotent_no_op(self):
        with TemporaryDirectory() as tmp:
            data_dir, run_dir = self._setup_run(tmp)
            restore_run(run_dir)

            result = restore_run(run_dir)

            self.assertEqual(result, {"restored": 0, "skipped": 2})

    def test_refuses_to_overwrite_existing_source(self):
        with TemporaryDirectory() as tmp:
            data_dir, run_dir = self._setup_run(tmp)
            # something now occupies abcd.set's original path
            (data_dir / "abcd.set").write_text("someone else's file")

            with self.assertRaises(QuarantineRestoreError):
                restore_run(run_dir)

            # efgh.set (processed after abcd.set) must be untouched
            self.assertTrue((run_dir / "efgh.set").is_file())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_quarantine -v`
Expected: FAIL — `ImportError: cannot import name 'restore_run'`

- [ ] **Step 3: Write minimal implementation**

Add to `rptsched_cleanup/quarantine.py`:

```python
class QuarantineRestoreError(RuntimeError):
    pass


def restore_run(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    rows = read_manifest(run_dir)
    restored = 0
    skipped = 0

    for row in rows:
        dest_path = Path(row["dest_path"])
        source_path = Path(row["source_path"])

        if not dest_path.exists():
            skipped += 1
            continue

        if source_path.exists():
            raise QuarantineRestoreError(
                "Cannot restore {}: source path {} already exists".format(row["filename"], source_path)
            )

        try:
            shutil.move(str(dest_path), str(source_path))
        except OSError as err:
            raise QuarantineRestoreError(
                "Failed to restore {}: {}".format(row["filename"], err)
            ) from err

        restored += 1

    return {"restored": restored, "skipped": skipped}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_quarantine -v`
Expected: PASS (9 tests total)

- [ ] **Step 5: Commit**

```bash
git add rptsched_cleanup/quarantine.py tests/test_quarantine.py
git commit -m "Add idempotent, resumable restore_run"
```

---

### Task 6: `find_orphan_groups`

**Files:**
- Create: `rptsched_cleanup/orphans.py`
- Create: `tests/fixtures.py`
- Test: `tests/test_orphans.py`

**Interfaces:**
- Consumes: nothing from `quarantine.py`.
- Produces: `find_orphan_groups(data_dir: Path) -> Dict[str, List[str]]` — parses `data_dir/schedlist` (pipe-delimited, field 0 is id) for the set of known ids; lists files in `data_dir` matching `^[a-z0-9]{4}\.(.+)$`, groups by id; returns `{id: [filenames]}` for every id **not** in the schedlist set. Files not matching the pattern are silently ignored. Also produces `tests/fixtures.py`'s `make_data_dir(base_dir: Path, schedlist_lines: List[str], extra_files: List[str]) -> Path`, used by this test and reused by the CLI test in Task 7-9.

- [ ] **Step 1: Write the failing test**

Create `tests/fixtures.py`:

```python
from pathlib import Path


def make_data_dir(base_dir: Path, schedlist_lines, extra_files) -> Path:
    """
    Build a data dir at base_dir/rptsched containing a schedlist file
    (one line per entry in schedlist_lines, already pipe-delimited) and
    an empty placeholder file for each name in extra_files.
    Returns the data dir path.
    """
    data_dir = Path(base_dir) / "rptsched"
    data_dir.mkdir(parents=True, exist_ok=True)

    with (data_dir / "schedlist").open("w") as f:
        for line in schedlist_lines:
            f.write(line + "\n")

    for filename in extra_files:
        (data_dir / filename).write_text("placeholder")

    return data_dir
```

Create `tests/test_orphans.py`:

```python
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rptsched_cleanup.orphans import find_orphan_groups
from tests.fixtures import make_data_dir


class TestFindOrphanGroups(unittest.TestCase):
    def test_finds_ids_with_no_schedlist_line(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "abcd|noverdue|Known Template|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            extra_files = [
                "abcd.set", "abcd.selans",  # has a schedlist line -> not an orphan
                "wxyz.set", "wxyz.user",    # no schedlist line -> orphan
                "schedid", "schedid.migr",  # not 4-char-id pattern -> ignored
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, extra_files)

            orphans = find_orphan_groups(data_dir)

            self.assertEqual(set(orphans.keys()), {"wxyz"})
            self.assertEqual(sorted(orphans["wxyz"]), ["wxyz.set", "wxyz.user"])

    def test_no_orphans_returns_empty_dict(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "abcd|noverdue|Known Template|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, ["abcd.set"])

            orphans = find_orphan_groups(data_dir)

            self.assertEqual(orphans, {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_orphans -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rptsched_cleanup.orphans'`

- [ ] **Step 3: Write minimal implementation**

Create `rptsched_cleanup/orphans.py`:

```python
import re
from pathlib import Path

ID_PATTERN = re.compile(r'^([a-z0-9]{4})\.(.+)$')


def find_orphan_groups(data_dir: Path):
    data_dir = Path(data_dir)
    schedlist_ids = set()

    with (data_dir / "schedlist").open() as f:
        for line in f:
            if not line.strip():
                continue
            schedlist_ids.add(line.split("|")[0])

    groups = {}
    for entry in data_dir.iterdir():
        if not entry.is_file():
            continue
        match = ID_PATTERN.match(entry.name)
        if not match:
            continue
        file_id = match.group(1)
        groups.setdefault(file_id, []).append(entry.name)

    return {file_id: filenames for file_id, filenames in groups.items() if file_id not in schedlist_ids}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_orphans -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add rptsched_cleanup/orphans.py tests/fixtures.py tests/test_orphans.py
git commit -m "Add find_orphan_groups orphan detection"
```

---

### Task 7: CLI — dry-run (default mode)

**Files:**
- Create: `remove_orphans.py`
- Test: `tests/test_remove_orphans_cli.py`

**Interfaces:**
- Consumes: `find_orphan_groups` (Task 6), `make_data_dir` fixture (Task 6).
- Produces: `build_parser() -> argparse.ArgumentParser` and `main(argv=None) -> int`, both importable from `remove_orphans` (the module, loaded via the `remove_orphans.py` file at repo root — tests import it as `import remove_orphans`). `--data-dir` and `--quarantine-dir` are both required arguments on the parser. With neither `--execute` nor `--restore` passed, `main` prints a dry-run summary to stdout and returns `0`, making no filesystem changes beyond what's already on disk.

- [ ] **Step 1: Write the failing test**

Create `tests/test_remove_orphans_cli.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_remove_orphans_cli -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'remove_orphans'`

- [ ] **Step 3: Write minimal implementation**

Create `remove_orphans.py`:

```python
#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

from rptsched_cleanup.orphans import find_orphan_groups


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove orphan files (no matching schedlist line) from a Symphony Rptsched directory."
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

    groups = find_orphan_groups(args.data_dir)
    total_files = sum(len(filenames) for filenames in groups.values())

    print("DRY RUN: {} orphan id(s), {} file(s) would be moved".format(len(groups), total_files))
    for file_id in sorted(groups):
        print("  {}: {}".format(file_id, ", ".join(sorted(groups[file_id]))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_remove_orphans_cli -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add remove_orphans.py tests/test_remove_orphans_cli.py
git commit -m "Add remove_orphans CLI with dry-run default mode"
```

---

### Task 8: CLI — `--execute` mode

**Files:**
- Modify: `remove_orphans.py`
- Test: `tests/test_remove_orphans_cli.py`

**Interfaces:**
- Consumes: `make_run_dir`, `move_groups_to_quarantine` (Task 1/3), `find_orphan_groups` (Task 6).
- Produces: `main` now handles `args.execute`: builds a timestamp via `datetime.now().strftime("%Y%m%d_%H%M%S")`, creates the run dir with prefix `"orphans"`, moves the groups, prints a summary, returns `0`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_remove_orphans_cli.py`:

```python
from rptsched_cleanup.quarantine import read_manifest


class TestExecute(unittest.TestCase):
    def test_execute_moves_files_and_writes_manifest(self):
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
                    "--execute",
                ])

            self.assertEqual(exit_code, 0)
            self.assertFalse((data_dir / "wxyz.set").exists())
            self.assertFalse((data_dir / "wxyz.user").exists())
            self.assertTrue((data_dir / "abcd.set").exists())

            run_dirs = list(quarantine_dir.glob("orphans_*"))
            self.assertEqual(len(run_dirs), 1)
            run_dir = run_dirs[0]
            self.assertTrue((run_dir / "wxyz.set").is_file())
            self.assertTrue((run_dir / "wxyz.user").is_file())

            rows = read_manifest(run_dir)
            self.assertEqual(len(rows), 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_remove_orphans_cli -v`
Expected: FAIL — execute mode still prints "DRY RUN" and moves nothing; `run_dirs` will be empty, assertion error.

- [ ] **Step 3: Write minimal implementation**

Modify `remove_orphans.py`:

```python
#!/usr/bin/env python3
import argparse
import sys
from datetime import datetime
from pathlib import Path

from rptsched_cleanup.orphans import find_orphan_groups
from rptsched_cleanup.quarantine import make_run_dir, move_groups_to_quarantine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove orphan files (no matching schedlist line) from a Symphony Rptsched directory."
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

    groups = find_orphan_groups(args.data_dir)
    total_files = sum(len(filenames) for filenames in groups.values())

    if not args.execute:
        print("DRY RUN: {} orphan id(s), {} file(s) would be moved".format(len(groups), total_files))
        for file_id in sorted(groups):
            print("  {}: {}".format(file_id, ", ".join(sorted(groups[file_id]))))
        return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = make_run_dir(args.quarantine_dir, "orphans", timestamp)
    move_groups_to_quarantine(args.data_dir, run_dir, groups, moved_at=timestamp)
    print("Moved {} file(s) across {} orphan id(s) into {}".format(total_files, len(groups), run_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_remove_orphans_cli -v`
Expected: PASS (3 tests total)

- [ ] **Step 5: Commit**

```bash
git add remove_orphans.py tests/test_remove_orphans_cli.py
git commit -m "Add --execute mode to remove_orphans CLI"
```

---

### Task 9: CLI — `--restore` mode

**Files:**
- Modify: `remove_orphans.py`
- Test: `tests/test_remove_orphans_cli.py`

**Interfaces:**
- Consumes: `restore_run` (Task 5).
- Produces: `main` now handles `args.restore`: calls `restore_run(args.restore)`, prints the restored/skipped counts, returns `0`. This branch is checked before orphan detection runs (restore doesn't need `find_orphan_groups` at all).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_remove_orphans_cli.py`:

```python
class TestRestore(unittest.TestCase):
    def test_restore_moves_files_back(self):
        with TemporaryDirectory() as tmp:
            schedlist_lines = [
                "abcd|noverdue|Known Template|n|200207021051|200507270844|SOMEMGR||||||0|3||0|$<library_notice:c>|ENGLISH|",
            ]
            data_dir = make_data_dir(tmp, schedlist_lines, ["abcd.set", "wxyz.set", "wxyz.user"])
            quarantine_dir = Path(tmp) / "quarantine"

            with redirect_stdout(io.StringIO()):
                remove_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            run_dir = list(quarantine_dir.glob("orphans_*"))[0]

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertTrue((data_dir / "wxyz.set").is_file())
            self.assertTrue((data_dir / "wxyz.user").is_file())
            self.assertIn("restored", out.getvalue().lower())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_remove_orphans_cli -v`
Expected: FAIL — `--restore` currently falls through to dry-run/orphan-detection logic (which doesn't touch quarantined files), so `wxyz.set`/`wxyz.user` remain missing from `data_dir` — assertion error.

- [ ] **Step 3: Write minimal implementation**

Modify `remove_orphans.py`:

```python
from rptsched_cleanup.quarantine import make_run_dir, move_groups_to_quarantine, restore_run


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.restore:
        result = restore_run(args.restore)
        print("Restored {} file(s), skipped {} already-restored".format(result["restored"], result["skipped"]))
        return 0

    groups = find_orphan_groups(args.data_dir)
    total_files = sum(len(filenames) for filenames in groups.values())

    if not args.execute:
        print("DRY RUN: {} orphan id(s), {} file(s) would be moved".format(len(groups), total_files))
        for file_id in sorted(groups):
            print("  {}: {}".format(file_id, ", ".join(sorted(groups[file_id]))))
        return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = make_run_dir(args.quarantine_dir, "orphans", timestamp)
    move_groups_to_quarantine(args.data_dir, run_dir, groups, moved_at=timestamp)
    print("Moved {} file(s) across {} orphan id(s) into {}".format(total_files, len(groups), run_dir))
    return 0
```

(Only the `import` line and the new `if args.restore:` block at the top of `main` are new; the rest of the function is unchanged from Task 8.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_remove_orphans_cli -v`
Expected: PASS (4 tests total)

- [ ] **Step 5: Commit**

```bash
git add remove_orphans.py tests/test_remove_orphans_cli.py
git commit -m "Add --restore mode to remove_orphans CLI"
```

---

### Task 10: Integration test against the real local sample data

**Files:**
- Test: `tests/test_remove_orphans_integration.py`

**Interfaces:**
- Consumes: `remove_orphans.main` (Task 9), the real `rptsched/` directory checked out locally at the repo root (227 ids, 40 known orphans, per prior manual analysis).
- Produces: nothing new — this is a read-only-in-effect sanity check that copies `rptsched/` into a temp dir first, so the real local dev copy is never mutated.

- [ ] **Step 1: Write the test**

Create `tests/test_remove_orphans_integration.py`:

```python
import io
import shutil
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import remove_orphans
from rptsched_cleanup.quarantine import read_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATA_DIR = REPO_ROOT / "rptsched"


@unittest.skipUnless(SAMPLE_DATA_DIR.is_dir(), "local rptsched/ sample data not present")
class TestRemoveOrphansAgainstSampleData(unittest.TestCase):
    def test_dry_run_matches_known_orphan_count(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "rptsched"
            shutil.copytree(SAMPLE_DATA_DIR, data_dir)
            quarantine_dir = Path(tmp) / "quarantine"

            out = io.StringIO()
            with redirect_stdout(out):
                exit_code = remove_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                ])

            self.assertEqual(exit_code, 0)
            self.assertIn("40 orphan id(s)", out.getvalue())

    def test_execute_then_restore_round_trips_cleanly(self):
        with TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "rptsched"
            shutil.copytree(SAMPLE_DATA_DIR, data_dir)
            quarantine_dir = Path(tmp) / "quarantine"

            files_before = sorted(p.name for p in data_dir.iterdir())

            with redirect_stdout(io.StringIO()):
                remove_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--execute",
                ])

            run_dir = list(quarantine_dir.glob("orphans_*"))[0]
            rows = read_manifest(run_dir)
            self.assertEqual(len(rows), 40 + sum(1 for _ in []))  # placeholder replaced below

            with redirect_stdout(io.StringIO()):
                remove_orphans.main([
                    "--data-dir", str(data_dir),
                    "--quarantine-dir", str(quarantine_dir),
                    "--restore", str(run_dir),
                ])

            files_after = sorted(p.name for p in data_dir.iterdir())
            self.assertEqual(files_before, files_after)


if __name__ == "__main__":
    unittest.main()
```

Fix the placeholder line before running: replace

```python
            self.assertEqual(len(rows), 40 + sum(1 for _ in []))  # placeholder replaced below
```

with:

```python
            self.assertGreater(len(rows), 0)
```

(The exact file count depends on how many companion files the 40 orphan ids have, which was already characterized during spec work as a mix of `set`-only, `set+user`, `set+am`, etc. — asserting `> 0` here is the meaningful check; the precise count is already covered by the dry-run summary count check in the other test.)

- [ ] **Step 2: Run test to verify it passes**

Run: `python3 -m unittest tests.test_remove_orphans_integration -v`
Expected: PASS (2 tests) if `rptsched/` is present locally; SKIPPED otherwise (e.g. in a CI environment without the gitignored sample data).

- [ ] **Step 3: Commit**

```bash
git add tests/test_remove_orphans_integration.py
git commit -m "Add integration test against local rptsched sample data"
```

---

## Self-Review Notes

- **Spec coverage:** dry-run default (Task 7), `--execute` with manifest + abort-on-failure (Tasks 3, 4, 8), `--restore` idempotent/resumable (Tasks 5, 9), orphan detection ignoring non-4-char-id files (Task 6), required `--data-dir`/`--quarantine-dir` (Task 7) — all covered. Manifest schema matches the spec's columns exactly (Task 2).
- **Type consistency:** `groups: Dict[str, List[str]]` (id → filenames, not full paths) is used consistently from `find_orphan_groups` (Task 6) through `move_groups_to_quarantine` (Task 3) through the CLI (Tasks 7-8). `run_dir` is always a `Path` returned by `make_run_dir` and consumed by `move_groups_to_quarantine`/`restore_run`/`read_manifest` unchanged.
- **Restore source-path conflict guard** (refusing to overwrite an already-existing `source_path`) was added in Task 5 beyond what the spec wrote out explicitly, since `shutil.move` would otherwise silently overwrite an existing file at the destination — flagging here since it's a safety addition, not a spec requirement, in case it should be reconsidered.
