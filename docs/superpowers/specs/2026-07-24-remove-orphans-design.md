# remove_orphans — Design Spec

## Purpose

Identify orphan file groups in the Symphony ILS `Rptsched` data directory —
`<id>.*` files with no corresponding line in `schedlist` — and remove them
from the live directory by moving them to quarantine (never deleting),
with a way to reverse the action if needed.

See `rptsched-domain-reference.md` for full domain background (what
`rptsched/` is, `schedlist` format, orphan definition, quarantine policy).
This spec covers only the orphan-removal script; stale saved templates and
scheduled-report removal candidates are separate specs, since those
require `schedlist` fields (owner, frequency, dates) that orphans don't
have. See `2026-07-24-remove-stale-templates-design.md` for the sibling
script this one shares its move/manifest/restore mechanics with — that
spec is the fuller reference for the shared module's contract, since it
had to work out schedlist-rewrite safety on top of the same mechanics.

## Inputs

Both required as CLI arguments, never hardcoded, so the same script runs
unmodified against a local test copy or the production directory:

- `--rptsched-dir` — path to the Rptsched directory (e.g. local `rptsched/`
  for testing, `/software/WYLD/Unicorn/Rptsched/` in production).
- `--quarantine-dir` — path to the quarantine directory (e.g.
  `/software/WYLD/Nic/Scripts/rptsched-cleanup/quarantine/`).

## Orphan detection

1. Parse `schedlist` in `--rptsched-dir`; collect field-0 (id) values into a
   set.
2. List files in `--rptsched-dir` matching `^([a-z0-9]{4})\.(.+)$`.
3. Group matched files by their 4-character id.
4. Any group whose id is **not** in the `schedlist` id set is an orphan.
   All files in that group (the `.set` plus any companions — `.user`,
   `.am`, `.srch`, `.id`, `.ids`, `.mn`, `.chk`, etc.) move together as
   one unit.

Files that don't match the 4-char-id pattern (`schedid`, `schedid.migr`,
timestamped `schedlist.*` backups, etc.) are always out of scope for this
script — ignored entirely, not reported. `schedid`/`schedid.migr` are
Symphony system files for the report-code counter; the timestamped
`schedlist.*` file is a stray backup unrelated to orphan cleanup.

## Modes

The script has three mutually exclusive modes, selected by flag:

### 1. Dry-run (default — no flag)

Scans and computes the orphan set, then prints a summary to the console:
each orphan id and its files. **Nothing is written or moved** — no
quarantine subfolder, no manifest, no changes to `--rptsched-dir`.

### 2. `--execute`

Performs the same scan, then:

1. Creates `--quarantine-dir` if it doesn't already exist.
2. Creates a new run subfolder inside it, named
   `orphans_<YYYYMMDD_HHMMSS>` (timestamp = script start time).
3. Moves every file in every orphan group from `--rptsched-dir` into that
   subfolder, flat (no further nesting), preserving original filenames.
4. Writes `manifest.csv` inside that same run subfolder, one row per file
   moved, columns:
   `id, filename, extension, source_path, dest_path, moved_at`
5. Prints a summary (orphan id count, file count, subfolder path).

**Error handling:** if any individual file move fails partway through the
run, the script aborts immediately — no further files are moved. The
manifest reflects only files successfully moved before the abort, and the
error is reported clearly (which file, why). Partial runs are safe to
inspect and safe to `--restore`, since the manifest only ever lists what
actually moved.

### 3. `--restore <run-subfolder>`

Given a path to a previous `--execute` run's subfolder (e.g.
`quarantine/orphans_20260724_143000`), reads that run's `manifest.csv` and,
for each row, moves the file back from `dest_path` to `source_path` — with
one exception: if a row's `dest_path` no longer exists, that file was
already restored by an earlier `--restore` attempt on this same
subfolder, so it's skipped rather than treated as an error.

This makes restore **idempotent and resumable**: if an individual move
fails partway through, the script aborts immediately, and whatever hasn't
been moved yet simply stays sitting in the run subfolder. That's the
status signal — a run subfolder that still contains files means restore
is incomplete; re-running `--restore` on the same subfolder is always
safe and picks up exactly where it left off.

`manifest.csv` is never deleted, during or after restore — once every
file has been moved back out, the subfolder is empty of data files but
still holds the manifest, which now doubles as: (a) proof the run
subfolder is fully restored (no files left to move), and (b) a permanent
audit record of what was removed and when.

## Explicitly out of scope

- Stale saved templates (`frequency_flag == "n"` + inactive) — separate
  script/spec.
- Scheduled report removal candidates (recurring + inactive) — separate
  script/spec.
- ACQ exclusion — not applicable; orphans have no `owner` field to check.
- Deleting the stray `schedlist.*` backup file or `schedid`/`schedid.migr`
  — not part of this script's job.
- Any dry-run output persisted to disk — dry-run is console-only by
  design (orphans are invisible from the Symphony interface either way,
  so the value of a persisted dry-run record is low; the persisted record
  that matters is the manifest from an actual `--execute` run).
