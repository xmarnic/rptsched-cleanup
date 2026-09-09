# sync_operator_field — Design Spec

## Purpose

Correct a data-integrity issue in the Rptsched directory: each saved
template's `<id>.set` file has an `operator|0|...|<VALUE>|` line that is
supposed to match that template's owner (`schedlist` field index 6 /
1-indexed field 7), but in the local sample data 56 of 187 templates
(30%) have drifted out of sync — including one case-only mismatch
(`wrigcircmgr` vs. `WRIGCIRCMGR`). A mismatch here is a potential source
of operational errors on report runs (the report executes as the wrong
operator), so this script scans every saved template, compares owner vs.
operator, and corrects the operator value in place to match `schedlist`
exactly — byte-for-byte, including case.

`schedlist`'s owner field is uppercase in all 5,311 production rows, so
exact-match correction also happens to enforce an implicit uppercase
standard, without any separate case-normalization logic.

Unlike `remove_orphans` and `remove_stale_templates`, nothing is moved
out of the data directory — the `.set` file must stay in place, with only
its operator line corrected. This script never touches `schedlist`.

See `rptsched-domain-reference.md` for `schedlist` format and field
definitions.

## Scope

- **In scope:** every saved template (every `schedlist` line), both
  manual (`frequency_flag == "n"`) and recurring templates. The
  operator/owner mismatch is a correctness issue unrelated to schedule
  type.
- **Out of scope — orphans.** `<id>.set` files with no matching
  `schedlist` line have no owner to sync from; skipped entirely, same as
  the other two scripts' treatment of orphans as a separate category.
- **Out of scope — inactivity rule.** Does not apply. This is a
  correctness fix, not a removal decision; every mismatch is corrected
  regardless of `last_run`/`created`.
- **Out of scope — ACQ exclusion.** Does not apply. ACQ's out-of-scope
  status in the other scripts is specific to removal decisions; it does
  not extend to data-integrity fixes.
- **Out of scope — SIRSI as a special case.** `SIRSI` is treated as an
  ordinary owner value, not a no-touch designation. When `schedlist`
  genuinely lists `SIRSI` as the owner (e.g. vendor-maintenance templates
  like `unauthload`/`globaledit`), operator already matches and is left
  alone. When a template's operator is stale-set to `SIRSI` but
  `schedlist` shows a real owner (observed case: `ykpp`, an active,
  recently-run CARB-library report), it is corrected like any other
  mismatch.

## Inputs

Both required as CLI arguments, never hardcoded:

- `--rptsched-dir` — path to the Rptsched directory.
- `--quarantine-dir` — path to the quarantine directory.

## Mismatch detection

For each `schedlist` line (id + owner field):

1. Locate `<id>.set` in `--rptsched-dir`. **If missing:** log a warning and
   skip this id — a missing `.set` file for an existing `schedlist` line
   is a separate data-integrity anomaly outside this script's job; do not
   abort the run over it.
2. Find the line matching `^operator\|` in the `.set` file. Format is
   consistently `operator|0|<optional>|<VALUE>|` — confirmed across all
   227 sample `.set` files (`<optional>` is usually empty, occasionally
   holds a value such as `SIRSI`, and is left untouched either way). The
   value to compare/replace is the second-to-last `|`-delimited segment.
   **If no line matches:** log a warning and skip this id (same handling
   as a missing `.set` file) — do not fabricate an operator line.
3. Compare the extracted value to `schedlist`'s owner field using exact
   string comparison (case-sensitive). If they differ, this id is a
   **mismatch** — a candidate for correction.

## Rewrite mechanics

In-place edit via write-temp-file-in-same-directory + atomic rename
(`os.replace`), never a direct in-place edit — the same pattern
`remove_stale_templates` uses for `schedlist`. Only the operator line's
value field changes; every other line and byte in the `.set` file passes
through unmodified.

## Modes

### 1. Dry-run (default — no flag)

Scans `schedlist`, applies mismatch detection, and prints each mismatch
to the console (`id`, `old_operator`, `new_operator`), plus a summary
count. **Nothing is written** — no quarantine subfolder, no manifest, no
changes to any `.set` file.

### 2. `--execute`

1. Re-runs mismatch detection.
2. Creates `--quarantine-dir` if missing, and a new run subfolder named
   `operators_<YYYYMMDD_HHMMSS>`.
3. For each mismatch, rewrites the `.set` file's operator line in place
   (temp-file + atomic rename), replacing only the value field.
4. Writes `manifest.csv` into the run subfolder as rewrites complete:
   `id, old_operator, new_operator`. No full-file backups — the manifest
   alone is sufficient to reverse a single-line change.
   **Abort-all on any individual rewrite failure** — stop immediately.
   Each individual rewrite is already atomic/durable, so files corrected
   before the failure stay corrected; the manifest only contains rows
   completed before the failure, so the run remains fully auditable and
   restorable up to that point.
5. Prints a summary (mismatch count, subfolder path).

### 3. `--restore <run-subfolder>`

Reads `manifest.csv`. For each row:

1. Read the current value of `<id>.set`'s operator line.
2. If it equals `old_operator`: already restored (by an earlier
   `--restore` attempt, or the file was independently reverted) — skip.
3. If it equals `new_operator`: this is the value the `--execute` run
   set — rewrite it back to `old_operator` (temp-file + atomic rename).
4. If it equals neither: something else changed the operator value since
   the `--execute` run. **Abort immediately** with an error rather than
   silently overwriting an edit this script didn't make.

This makes restore idempotent and resumable: re-running `--restore` on
the same subfolder after a partial failure is always safe, since already
restored rows are skipped on the next attempt.

`manifest.csv` is never deleted, during or after restore — it is both the
restore's driver and the permanent audit record of what was corrected and
when.

## Explicitly out of scope

- Orphans (no `schedlist` line) — not templates, no owner to sync from.
- The inactivity rule and ACQ exclusion — not applicable to a correctness
  fix (see Scope above).
- `schedlist` itself — never read for anything but the id/owner pair,
  never written.
- `.selans` files — confirmed to carry no operator/owner information;
  not touched.
- Any locking/concurrency protection against Symphony's own scheduler
  process reading/writing `.set` files at the same moment — out of scope
  for this spec; atomic rename is the only safety mechanism specified.
