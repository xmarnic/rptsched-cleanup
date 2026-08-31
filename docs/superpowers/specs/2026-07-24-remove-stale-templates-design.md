# remove_stale_templates — Design Spec

## Purpose

Identify **stale saved templates** in the Symphony ILS `Rptsched` data
directory — manually-run (`frequency_flag == "n"`) saved templates that
satisfy the inactivity rule — and remove them from the live directory:
quarantine their files (never delete) and remove their line from
`schedlist`, keeping the data directory internally consistent. Provide a
way to reverse the action.

See `rptsched-domain-reference.md` for full domain background (`schedlist`
format, inactivity rule, trustworthy vs. untrustworthy mtimes). See
`2026-07-24-remove-orphans-design.md` for the sibling script this one
shares its move/manifest/restore mechanics with.

This spec covers only stale (manual) templates. Scheduled report removal
candidates (recurring `frequency_flag`, otherwise the same inactivity
rule) are handled by a separate script/spec, since — per the domain doc —
a recurring template staying inactive doesn't mean the same thing
operationally as a manual one going unused.

## Inputs

Both required as CLI arguments, never hardcoded:

- `--data-dir` — path to the Rptsched directory.
- `--quarantine-dir` — path to the quarantine directory.
- `--years` (optional, default `3`) — override for the inactivity
  threshold, for testing the logic against different windows. Production
  runs should rely on the default, which matches the domain doc's policy.
- `--exclude-owner OWNER` (optional, repeatable) — exclude templates whose
  `owner` field is an exact, case-insensitive match for `OWNER`. No
  substring matching, no surprises: excludes only the literal owner(s)
  named.
- `--exclude-owner-regex PATTERN` (optional, repeatable) — exclude
  templates whose `owner` field matches regex `PATTERN` via
  case-insensitive, unanchored `re.search`. Breadth is the caller's
  responsibility via regex syntax (e.g. `ACQ` matches anywhere in the
  owner, `^ACQ` matches only owners starting with it).

Neither flag has a built-in default — this tool ships with zero owner
exclusions unless a caller passes one. Any site-specific default (e.g.
WYLD excluding all ACQ-owned templates via `--exclude-owner-regex ACQ`)
lives in that site's own invocation/wrapper, not in this script or the
shared library.

## Candidate selection

A saved template (a `schedlist` line) is a **removal candidate** if all
of the following hold:

1. `frequency_flag == "n"` (manual — not on a recurring schedule).
2. Inactivity rule (using `--years`, default 3):
   `last_run != 0000000000 AND last_run is --years+ before today`
   `OR`
   `last_run == 0000000000 AND created is --years+ before today`
3. `owner` is not excluded by any `--exclude-owner` (exact match) or
   `--exclude-owner-regex` (regex match) entry passed on the command
   line.

"Today" is the script's run date.

## Modes

### 1. Dry-run (default — no flag)

Scans `schedlist`, applies candidate selection, and prints a summary line
— stale-candidate count, total manual-template count in `schedlist`
(regardless of staleness or owner exclusion), and file count — followed
by each candidate's id, description, owner, frequency_flag,
last_run/created, and its files on disk. **Nothing is written or
moved** — no quarantine subfolder, no manifest, no changes to
`schedlist` or `--data-dir`.

### 2. `--execute`

1. Re-runs candidate selection.
2. Creates `--quarantine-dir` if missing, and a new run subfolder named
   `templates_<YYYYMMDD_HHMMSS>`.
3. Moves every file belonging to each candidate id (the `.set` plus any
   companions, matched by 4-char-id prefix exactly as in the orphans
   script) into that subfolder, flat, preserving filenames.
   **Abort-all on any individual move failure** — if one file fails to
   move, stop immediately; no schedlist changes happen in this case,
   since schedlist is only rewritten after every move succeeds.
4. Once every file move succeeds, writes two files into the run
   subfolder:
   - `manifest.csv` — one row per file moved: `id, filename, extension,
     source_path, dest_path, moved_at` (same shape as the orphans
     manifest).
   - `removed_schedlist_lines.txt` — the exact, verbatim, pipe-delimited
     `schedlist` lines that were removed, one per line, unmodified. This
     is the source of truth for restoring schedlist state, not
     `manifest.csv`.
5. Rewrites `schedlist` in `--data-dir`: build the new content by
   filtering out the candidate lines, write to a temp file in the same
   directory, then atomically replace the live `schedlist` (write-temp +
   rename, never an in-place edit) — so a crash mid-write can't leave
   `schedlist` truncated or corrupted.
6. Prints a summary (candidate count, file count, subfolder path).

### 3. `--restore <run-subfolder>`

Two phases, files before schedlist — mirroring execute's own ordering —
and both phases are idempotent, so the whole operation is safely
resumable if it's interrupted or partially fails.

**Phase 1 — files.** Reads `manifest.csv` and, for each row, moves the
file back from `dest_path` to `source_path` — unless `dest_path` no
longer exists, meaning that row was already restored by an earlier
attempt, in which case it's skipped. If an individual move fails, abort
immediately; whatever hasn't moved yet stays in the run subfolder, which
is the signal that restore is incomplete (safe to just re-run `--restore`
on the same subfolder again). Phase 2 only begins once every file from
the manifest has been confirmed moved out.

**Phase 2 — schedlist.** Reads `removed_schedlist_lines.txt`. For each
line, checks whether its id is already present in the **current** live
`schedlist` — if so (already restored by an earlier attempt, or a
template with that id was independently recreated since), skip it rather
than insert a duplicate; a schedlist id must stay unique. Otherwise insert
it. This is a targeted re-insertion into the current file, not a blind
overwrite with a backup copy — the current file may have legitimate edits
made since the removal run (e.g. new templates added by staff), and
restore must not discard those. After inserting, place each restored line
at the position matching its `created` timestamp among the surrounding
lines, without disturbing the relative order of any line that wasn't
touched — `schedlist`'s real on-disk order is chronological by `created`
(append order), not alphabetical by id. (An earlier version of this spec
assumed id order; confirmed wrong and fixed via a local execute→restore
round-trip test — see CLAUDE.md and
`docs/testing/2026-08-31-run-behavior-test-procedure.md`.) Write via the
same temp-file + atomic-rename approach as `--execute`.

`manifest.csv` and `removed_schedlist_lines.txt` are never deleted,
during or after restore. Once phase 1 completes, the run subfolder is
empty of data files but still holds both — which then double as: (a)
proof the run is fully restored (nothing left to move), and (b) a
permanent audit record of what was removed and when.

## Shared mechanics with the orphans script

The following logic is common to both `remove_orphans` and
`remove_stale_templates` and should live in one shared internal module,
not be duplicated:

- Given a data-dir, quarantine-dir, a run-name prefix (`orphans` or
  `templates`), and a set of target ids: create the timestamped run
  subfolder, move each id's file group into it, write `manifest.csv`.
- The restore-files-from-manifest step (move `dest_path` back to
  `source_path`, skipping rows already restored, aborting on individual
  failure) — idempotent and resumable by design, and `manifest.csv` is
  never deleted so it always doubles as both the completeness signal and
  the audit record.

What is **not** shared — each script keeps its own:

- Candidate/orphan detection logic (different selection criteria
  entirely).
- Whether/how `schedlist` gets touched (orphans never touch it;
  stale-templates rewrites it both on execute and restore).

Scripts must not invoke each other or share detection logic — e.g.
`remove_stale_templates` must not, after rewriting `schedlist`, hand off
to `remove_orphans`'s "sweep all current orphans" detection to move the
now-orphaned files. That would silently catch unrelated pre-existing
orphans in a `templates_<timestamp>` run and mix two operations under one
manifest. It builds its own list of exactly the candidate ids selected in
step 1 and moves only those.

## Explicitly out of scope

- Scheduled report removal candidates (recurring + inactive) — separate
  script/spec.
- Orphans — separate script/spec, already written.
- Any locking/concurrency protection against Symphony's own scheduler
  process reading/writing `schedlist` at the same moment — out of scope
  for this spec; atomic rename is the only safety mechanism specified.
