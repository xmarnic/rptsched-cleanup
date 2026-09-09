# Composable CLI pipeline — Design Spec

## Status

Cross-cutting infrastructure spec, spanning all three detection
categories (orphans, stale templates, operator sync) plus `run_all.py`.
Same kind of document as `2026-07-24-run-all-design.md` in that it isn't
a single category's detection spec — but this one supersedes parts of
that document (`run_all.py` itself) and touches every script's CLI shape
described in `2026-07-24-remove-orphans-design.md`,
`2026-07-24-remove-stale-templates-design.md`, and
`2026-07-24-sync-operator-field-design.md` (all three keep their
detection logic and quarantine/manifest/restore mechanics as specified
there — this document is about how the *tools themselves* are shaped and
composed, not about what counts as a removal candidate). No code changes
yet; this is the design to build against.

## Problem statement

`tools/schedlist_report.py`, a read-only analysis companion to
`remove_stale_templates.py`, calls the exact same detection functions
(`activity_index.build_activity_index`, `templates.find_stale_template_candidates`)
against the exact same inputs as `remove_stale_templates.py`'s dry run —
deliberately, so its numbers can't drift from what a real dry run would
report. But it does so as a fully separate process, and pays the full
cost of decoding `Logs/Hist/` (`logprint | translate` shelled out per
file, the expensive part of activity-index construction) independently
every time, in a cache namespace uncoordinated with either of the other
two places the same computation happens:

| Invocation | Cache location | Behavior |
|---|---|---|
| `schedlist_report.py` (any run) | `--work-dir/activity_index_cache.json` | Own cache, reused across its own runs |
| `remove_stale_templates.py` dry run | none — `remove_stale_templates.py:120-126` explicitly passes `cache_path=None` | Full rescan every single invocation, on purpose, to satisfy "dry run writes nothing" |
| `remove_stale_templates.py --execute` | `{quarantine_dir}/activity_index_cache.json` | Own cache, first hit after a dry run still pays full cost |

Three cache namespaces, one underlying computation, computed cold up to
three times in a normal review-then-execute session.

This isn't a caching bug to patch in isolation — it's what happens when
every script bundles argument parsing, detection, presentation, and
mutation into one process. Nothing composes, because "compute the
candidate list" isn't a separable step from "print it" or "act on it" in
any of the four scripts today. `run_all.py` fakes composition by
importing the other three scripts and calling their `main(argv)`
in-process with rebuilt argv lists (`run_all.py:7-15`, `:59-73`) —
sequencing, not real separation; nothing flows between the three calls
except a shared log tee and a stop-on-failure check.

## Current-state audit

### `remove_orphans.py` + `rptsched_lib/orphans.py` — the clean reference case

Detection: `orphans.find_orphan_groups(data_dir)` (`orphans.py:7-27`) —
reads `schedlist` for the set of known ids, scans `data_dir` for
`<id>.*` groups not in that set. Plumbing: fully delegates to
`rptsched_lib/quarantine.py` — `make_run_dir`, `move_groups_to_quarantine`,
`restore_run`, no local reimplementation of any of it
(`remove_orphans.py:33-58`). Never touches `schedlist` content, only
reads it. This is the shape the other two scripts should have converged
on and didn't.

### `remove_stale_templates.py` — quarantine mechanics plus schedlist rewrite

Same quarantine.py plumbing as orphans, plus its own `schedlist`
mutation layered on top: `rptsched_lib/schedlist.py`'s `remove_lines`/
`insert_lines` (atomic replace), with a `removed_schedlist_lines.txt`
sidecar recording the exact removed lines so `--restore` can re-insert
them at the position matching their `created` timestamp, idempotent by
id. This extra layer is why stale-templates' restore is more involved
than orphans' — restoring files isn't enough, the schedlist row has to
come back too, into whatever the *current* schedlist looks like, not by
overwriting it.

### `sync_operator_field.py` + `rptsched_lib/operators.py` — the drifted outlier

This script does not fit the orphans/stale-templates shape at all, and
that's legitimate (it edits a `.set` file's `operator|` field in place;
there's no file to move to quarantine), but it also independently
reinvented plumbing that should have been shared:

- Its own CSV manifest read/write (`operators.py:99-129`) — same
  `manifest.csv` filename and same `csv.DictWriter`/`DictReader`
  approach as `quarantine.write_manifest`/`read_manifest`, different
  field schema, separate `InvalidManifestError`. `quarantine.read_manifest`
  itself does **no** header validation at all today — the exact gap
  `operators.py`'s validation exists to cover, just not shared.
- Its own atomic-write helper (`operators.py:63-74`) — structurally
  identical (mkstemp + copystat + os.replace) to `schedlist.py`'s
  private `_atomic_write`, copy-pasted rather than extracted.
- Its own restore logic (`sync_operator_field.py:35-73`) — a 3-way
  compare against the *current* live value of the field: matches the
  manifest's `old_operator` → already original, skip; matches
  `new_operator` → rewrite back to old, restored; matches neither →
  abort loudly, someone else touched it since. Genuinely different
  shape from `quarantine.restore_run`'s existence-check-and-skip
  (there's no file to check existence of), so this one stays separate —
  but see "Shared plumbing" below for what should still be generalized.

### `run_all.py` — sequencing, not composition

Imports the other three scripts, rebuilds an argv list per script
(`_build_argv`/`_build_template_argv`, `run_all.py:59-73`), calls each
`main(argv)` in fixed order, tees stdout/stderr to a log file for the
duration, stops on first nonzero exit. No detection or plumbing of its
own. **Retired by this design** (see below) — replaced by documenting an
equivalent shell pipeline directly in CLAUDE.md, since real Unix tools
compose via the shell, not via one script importing and argv-simulating
three others in-process.

### `tools/schedlist_report.py` — half of the target shape, already

Copies `--data-dir` before reading anything (`schedlist` is a single
flat-file index for the entire report scheduler — not a file to risk
touching directly for a read-only tool), calls the same detection
functions `remove_stale_templates.py` calls, and only then formats a
report. This is already "detect, then report, as separate concerns" in
spirit — it just isn't split into two actual processes yet, and its
cache is its own island rather than shared with the other two
invocations of the identical computation.

## Design goals

1. Each tool does one thing: detect, report, execute, or restore — never
   more than one, per category.
2. Composability via a stable data contract, not via one script calling
   another's `main()`.
3. The same detection computation is never redone from a cold cache when
   a warm one already exists for the same inputs.
4. Every existing safety guarantee (dry-run writes nothing to production
   paths; quarantine is always a move, never a delete; `--restore` is
   idempotent and resumable; schedlist restore preserves creation order)
   survives the move from single-process control flow to composed,
   separately-invoked stages — restated explicitly below, since nothing
   enforces them structurally anymore once composition is real.

## The data contract: JSONL candidate stream

One JSON object per candidate, one per line, one stream per category.
Chosen over CSV specifically because `filenames` (a list) and similar
per-category fields don't fit a flat column schema without a secondary
delimiter hack — JSONL handles this natively with the stdlib `json`
module, while staying line-oriented and streamable/greppable like any
other Unix text stream.

Every record carries a `schema_version` field. A reviewed file is meant
to sit around for a while awaiting sign-off (that's the point of the
review gate) — if `detect`'s schema changes in the meantime, `execute`
must hard-error on a version it doesn't recognize rather than
silently misinterpreting stale field names.

Indicative per-category fields (finalized at implementation time, not
frozen here):

- **stale-templates**: `id`, `report_source`, `description`, `owner`,
  `frequency_flag`, `created`, `raw_line`, `filenames`
- **orphans**: `id`, `filenames`
- **operators**: `id`, `old_operator`, `new_operator`

`raw_line` (the literal `schedlist` line) is included for stale-templates
specifically because it's the single field whose exact-string equality
transitively covers every other schedlist-derived field at once — see
the diff mechanics below.

## The four stages, per category

### `detect-<category>`

Pure detection, nothing else. The CLI layer copies `--data-dir` first
(matching what `schedlist_report.py` already does, for the same reason —
`schedlist` is too sensitive to read from a script that might one day
also write) and calls a **copy-free core library function** to do the
actual detection. The copy is a thin CLI-level wrapper around that core
function, not baked into it — deliberately, so `execute`'s internal
re-detect (below) can call the same core function directly against live
`--data-dir` without paying a second ~12,000-file copy on every mutating
run, immediately before it's about to mutate that same live directory
anyway under its own atomic-write discipline.

Emits JSONL to stdout. Writes nothing else — except, for stale-templates,
the shared activity-index cache (see "Guarantee re-statements" below for
why that's a deliberate, stated exception and not a regression).

### `report-<category>`

Reads a JSONL stream (stdin or a file) plus `--data-dir` as a required
companion argument. Taking a filesystem argument alongside a stream is
ordinary Unix practice, not a purity violation — `grep -f patternfile`,
`rsync --files-from=list src dst` do the same.

For stale-templates specifically: the "active functional duplicates"
section (comparing `.set` files byte-for-byte, within owner, among
*active* — non-candidate — templates, to catch cases the activity
index's `(report_source, description)` join key is too coarse to see)
is **not** purely stream-derived. It independently re-scans `schedlist`
for the active population and does its own pairwise comparison, fresh,
on every invocation — this is intentional and stated explicitly rather
than left as an inconsistency: it's cheap (a `schedlist` scan and some
file diffs, no `Logs/Hist/` decode involved), so redoing it isn't the
kind of redundancy this design is trying to eliminate. Also stated
explicitly: `report`'s filesystem reads are a fresh, uncoordinated
snapshot relative to the JSONL stream it's also consuming — if a `.set`
file changes between `detect` and `report`, the report's characterization
of it may be mildly stale by the time a human reads it. Since `report`
never mutates anything, this is an accepted staleness window, not a bug
to fix.

### `execute-<category>`

Reads a **reviewed** JSONL file — the literal artifact a human signed
off on — plus `--data-dir` and `--quarantine-dir`. Before mutating
anything:

1. Re-runs `detect-<category>`'s core (copy-free) function fresh
   against live `--data-dir`.
2. Diffs the reviewed file against the fresh result **per-ID, not as
   whole-stream equality**:
   - A reviewed ID missing from the fresh result, or present in both but
     with a changed `raw_line` (stale-templates) or equivalent identity
     field (other categories) → **abort loudly, nothing written.**
     Something changed since review.
   - A fresh-only ID (a *new* candidate that wasn't in the reviewed
     file) → ignored. `execute` only ever acts on what was reviewed;
     new candidates simply wait for the next review cycle.

   This scoping is required, not a nicety: whole-stream equality would
   abort every time an *unrelated* `schedlist` row changes between
   review and execute — in a live production directory, that's the
   common case, not an edge case. Comparing per-ID against exact field
   values (via `raw_line` for stale-templates, which covers every
   schedlist-derived field in one string compare) also catches, for
   free, a human hand-editing a field in the reviewed file rather than
   striking a record out entirely — no separate "reviewed-file integrity"
   mechanism is needed beyond this diff already being exact-match.
3. The diff check strictly **precedes** `make_run_dir`. An abort must
   never leave an orphaned, manifest-less run directory behind — that
   would silently violate "every run directory has a manifest," which
   `--restore`'s resumability assumes.
4. On a clean diff, mutate using the shared plumbing (quarantine move,
   or the operator field rewrite) and persist restore-support data
   (stale-templates' `removed_schedlist_lines.txt`) from the **fresh
   re-detect's** field values — never from the reviewed file's. The
   reviewed file is authorization (which IDs are approved), never the
   source of what actually gets written; using its values instead of
   the fresh ones would risk persisting a stale `raw_line` into the
   restore sidecar, which `--restore` would then reinsert as if current.

For operator-sync specifically: its pre-mutation check isn't a flat
equality diff, it's the same 3-way comparison its own restore logic
already uses, just with the two directions swapped — current value
matches the reviewed `old_operator` → proceed; matches `new_operator`
already → idempotent, skip without erroring; matches neither → abort,
someone else touched it. `execute-operators` and `restore-operators`
should share this comparison as one function — not previously
identified as shared, since today only restore has it.

### `restore-<category>`

Orphans and stale-templates share `quarantine.restore_run` unchanged —
existence-check-and-skip is category-agnostic file-move logic, and stays
that way. Operator-sync keeps its distinct 3-way restore (see above),
now sharing its comparison logic with `execute-operators`' pre-check
rather than existing only in one place.

### `build-activity-index` (stale-templates only)

The one category with an expensive, incrementally-cacheable detection
step gets its own tiny tool whose entire job is keeping **one canonical
`--index-cache-path`** current — `detect-stale-templates` and
`execute-stale-templates`'s internal re-detect both point at it, instead
of today's three fragmented, uncoordinated cache locations. This is the
direct fix for the redundancy in the problem statement.

`activity_index._load_cache`/`_save_cache`'s read-modify-write is atomic
*per save* (via `os.replace`) but not atomic *across* concurrent writers
— two processes touching the same cache path close together (e.g. a
scheduled `build-activity-index` run overlapping an interactive
`detect | report`) can each load a version, add their own newly-decoded
entries, and whichever saves last wins, discarding the other's work.
Stated guarantee: **safe, but may redundantly redo a decode; never
corrupts the cache.** A stdlib-only advisory lock (`fcntl.flock` — POSIX,
fine on the RHEL8 production target) is the noted mitigation if
concurrent invocation turns out to matter in practice. Not built
preemptively — out of scope for this pass.

## Shared plumbing generalization

Two pieces of duplication found in the audit get collapsed, without
forcing the two categories' genuinely different *restore* semantics into
one shape:

**Manifest CSV I/O.** Generalize into
`write_manifest(run_dir, fieldnames, rows)` /
`read_manifest(run_dir, fieldnames)`, header-validated on read (raising
on mismatch). This closes two gaps at once: `quarantine.py`'s current
`read_manifest` has no validation at all, unlike `operators.py`'s; and
`operators.py` stops maintaining a parallel copy of the same CSV
mechanics. `quarantine.py` and `operators.py` both become thin callers
passing their own `MANIFEST_FIELDS`. Restore logic itself is
deliberately **not** unified into one dispatcher — move-based and
value-compare restore don't share enough to be worth the indirection,
and this codebase's existing style favors plain functions over
strategy-pattern abstractions for two call sites.

**Atomic write.** The same ~10-line mkstemp+copystat+os.replace pattern
exists independently in `schedlist.py`'s private `_atomic_write`,
`operators.py`'s private copy, and inline in
`activity_index.py:_save_cache` — three copies today, with a fourth and
fifth about to appear (`execute-orphans`, `execute-stale-templates`,
`execute-operators`, and `build-activity-index` all need to write
something atomically). One shared `atomic_write(path, content)` helper,
stdlib-only, used everywhere instead.

## Guarantee re-statements

Each of these was previously true because a single process's control
flow made the alternative unreachable. Composition means each one now
needs restating as an explicit property of the split design, not an
accident of one script's internals:

| Guarantee | Status under the split |
|---|---|
| Dry-run writes nothing | **Re-scoped, deliberately.** `detect`/`report` write nothing to `--data-dir` or `--quarantine-dir` — but `detect-stale-templates` *does* write to the shared `--index-cache-path` by design, since that's disposable derived cache state, not production data or an audit artifact. Stated here explicitly so it reads as an intentional exception, not a silent regression from today's literal "writes nothing" wording. |
| Quarantine is always a move, never a delete | Unchanged — enforced entirely inside `execute`/`quarantine.py`, untouched by the split. |
| `--restore` is idempotent and resumable | Unchanged mechanically, but now depends on a sequencing rule that didn't need stating before: the execute-time diff check must precede `make_run_dir`, so an abort never leaves a manifest-less run directory that would violate "every run dir has a manifest." |
| Schedlist restore preserves creation order, idempotent by id | Unchanged mechanically, but now depends explicitly on `execute` persisting the restore sidecar from the **fresh re-detect's** values, not the reviewed file's — stated as a hard requirement here so a future simplification doesn't quietly source it from the reviewed file instead (they'll usually match, which is exactly what would make the bug hard to notice). |
| *(new)* Reviewed-file field tampering is caught | Falls out of the per-ID exact-field diff for free — a hand-edited field, not just a struck-out record, gets rejected the same way schedlist drift does. |
| *(new)* Shared activity-index cache under concurrent writers | Safe, never corrupts; may redundantly redo a decode. See `build-activity-index` above. |

## `run_all.py` retirement

Deleted outright. CLAUDE.md documents the equivalent shell pipeline in
its place. One concrete regression risk to solve in that documentation,
not leave implicit: a naive `detect-x | report-x` pipe does **not**
propagate a failing `detect` the way `run_all.py`'s explicit per-script
exit-code check did — a `detect` that fails and prints nothing still
lets `report` process an empty stream and exit 0, masking the failure.
The documented pipeline must use `set -o pipefail` (bash-specific —
confirm the production invocation shell is actually bash, not a plain
POSIX `sh`/`dash`, before relying on it) or explicit
`${PIPESTATUS[@]}` checks.

## Rollout phasing (intent, not committed work)

1. Stale-templates first — highest-value target, `schedlist_report.py`
   already half-shaped this way.
2. Shared manifest/atomic-write generalization — unblocks operator-sync
   with no behavior change to orphans, which is already aligned.
3. Orphans converts last — trivial, already clean.
4. `run_all.py` retirement lands once the last category converts.

## Explicitly out of scope

- Exact final JSONL field names/types per category — implementation-time
  detail, not frozen here.
- Whether `report` ever becomes fully generic across categories instead
  of category-specific — current lean is category-specific, since what's
  worth reporting genuinely differs per category.
- Building the concurrent-cache lock preemptively — noted as a
  mitigation to reach for if contention becomes a real problem in
  practice, not built speculatively.
- Rewriting CLAUDE.md's "Cleanup scope" section to describe the new
  multi-binary-per-category shape and the replacement shell pipeline —
  necessary follow-up, done at implementation time, not in this spec.
