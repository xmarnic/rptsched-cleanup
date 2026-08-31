# remove_stale_templates — Redesign: log-based detection

## Status

Supersedes the candidate-selection logic in
`2026-07-24-remove-stale-templates-design.md` (still the reference for
everything about modes, quarantine/manifest/restore mechanics, and CLI
shape — none of that changes here). This document covers **only** what
counts as a removal candidate and why the original rule doesn't work.

This is a revision of an earlier version of this same document, which
described a `Logs/Report/`-only design. That version is superseded by
this one: subsequent investigation (see
`2026-08-31-report-log-data-sources-and-tagging-roadmap.md` for the full
empirical record) found a second, owner-attributed source
(`Logs/Hist/`) that closes most of the ambiguity the `Logs/Report/`-only
design had to work around operationally (renaming templates, an
observation window, etc.) — all of that operational rollout plan is
dropped in favor of using both sources directly.

## Why the original rule is broken, not just mistuned

The original spec's inactivity rule trusted `schedlist`'s `last_run`
field (falling back to `created` when never run) as a proxy for real
usage. Production tickets reported templates removed under that rule
that were, per the owning staff, still in active use — `efwj`
(`TS2bibload`) and `qmod` (`TS2orderload`), both owned by NATRBIBMGR.

Direct empirical testing — full procedure and evidence in
`docs/testing/2026-08-31-run-behavior-test-procedure.md` — found the rule
isn't just occasionally wrong, it's structurally blind to the most common
usage pattern for a manual (`frequency_flag == "n"`) template:

- Ad hoc "Run Now" (Setup and Schedule menu, or double-click) **never**
  updates a manual template's own `last_run`, on any report type tested,
  on both the test server and directly on production.
- Scheduling anything on a manual template — ASAP, one-time ("run once"
  → `frequency_flag = "o"`), daily, weekly — **also never touches the
  original row**. Each spawns a brand-new `schedlist` row under a fresh
  id instead. Only that new row's own `last_run` updates correctly once
  its schedule actually fires — confirmed directly (`kdlt`/`kdlu` test
  templates, both fired and updated in place, on production).

So a manual template's `last_run`/`created` cannot answer "is this being
used," full stop — not for one report family, for all of them. This
isn't a threshold problem; the field doesn't carry the information the
original rule needed. `created` remains trustworthy for one narrow
purpose only: a genuine one-time creation stamp on `"n"` rows specifically
(see `rptsched-domain-reference.md`'s field-4 caveat) — used below only
as a recency floor for brand-new templates, never as an activity signal.

## The real signal: two independent log sources

Two data sources outside `rptsched/` record actual report execution,
with different strengths. Both are read-only inputs to this tool —
neither is ever written to, moved, or modified.

### `Logs/Report/` — unconditional, no owner

`/software/WYLD/Unicorn/Logs/Report/`: current month uncompressed
(`YYYYMM.log`) plus a same-day daily file, prior months compressed
(`YYYYMM.log.Z`, Unix `compress` format — not gzip, needs `zcat` not
`gzip`). Confirmed present back to at least January 2021.

Every report execution — ad hoc or scheduled, no exceptions found in
testing — produces:
```
YYYYMMDDHHMMSS Starting report <report_type>:"<description>"
YYYYMMDDHHMMSS Adding report <report_type>:<description> to finished list
YYYYMMDDHHMMSS Finished report <report_type>:"<description>"
```
Plain text, no decode step, ever. This is a **completion** signal — it
proves a report finished, not just that someone requested one. Cheap
enough to parse in full on every run; probably doesn't need incremental
caching.

No owner field. Join key is `(report_type, description)` only.

### `Logs/Hist/` — owner-attributed, catches ad hoc, longer retention

`/software/WYLD/Unicorn/Logs/Hist/`: `YYYYMM.hist(.Z)`, confirmed
present back to at least June 2014 (12+ years). This is Symphony's
general transaction audit log — not report-specific — so it mixes in
every transaction type the system handles, at far higher volume than
`Logs/Report/`.

**Raw format**: every transaction line carries its command as a
2-character code directly after a `^S<seq>` sequence number, e.g.
`^S93goFF17TECH...`. Confirmed against real production data (see the
roadmap doc's command-code table) — the codes relevant to report
scheduling:

| code | command | signal value |
|---|---|---|
| `ge` | Create Scheduled Report | commit/save event — carries frequency (including **`"a"` = ad hoc**, never persisted to `schedlist` but logged here), owner, id, report_type, description. The only source that sees ad hoc "Run Now" at all. |
| `gg` | Modify Scheduled Report | edits to an existing schedule, including `suspend status`. |
| `gh` | Remove Scheduled Report | schedule deletion. |
| `gk` | Remove Finished Report | fires when a user dismisses a completed report from Finished Reports; carries `login of the owner of the report` — the authoritative owner field, distinct from the acting user. Conditional (auto-delivered reports may never trigger it) — a corroborator, not a replacement for `Logs/Report/`'s unconditional signal. |
| `gu` | Rename Scheduled Report | carries `oS:<old_id>`, linking to the schedule's own previous generation only — **not** back to the manual template that originally spawned it. |

**Performance strategy**: pre-filter raw text for these codes
(`\^S[0-9]+g[ehgku]`) *before* ever decoding — this needs no
`logprint`/`translate` call at all for classification, only for
extracting field values from the already-narrowed subset:
```
zcat 202101.hist.Z | rg "\^S[0-9]+g[ehgku]" | logprint | translate
```
Reduction magnitude confirmed with real data: the looser `^oa` marker
(present on these lines but not exclusive to them) matches only ~1.74%
of raw lines across 31 sampled months (~57.5x fewer lines to decode);
the code-based filter is a strict subset of that, so at least as good.
Format stability confirmed representative across the full 3-year window
via one day's file — `^S<seq><code>` is a fixed Symphony-internal
transaction-log structure, not something that drifts month to month.

Decoded field mapping (via `logprint | translate`): `^oa`=schedule id,
`^ob`=report_type, `^oc`=description, `^od`=frequency, `^of`=last-run,
`^FW`=acting user, `^FD`=station type.

Set Report Options (`go`, dialog-navigation noise) and Search Order Part
B (an unrelated ACQ command sharing the `"schedule id:"` decoded label)
are explicitly excluded — filtering by the raw command code rather than
decoded text avoids picking up either.

## The join-key problem is mostly solved without tagging

The earlier version of this document treated id-tagging as the fix for
`Logs/Report/`'s ambiguous `(report_type, description)` collisions (15%
of manual templates, concentrated in un-customized descriptions like
bare `"TS2bibload"`). With `Logs/Hist/`'s owner attribution available,
`(report_type, description, owner)` resolves the same-day-generated
ambiguity for any template with activity recorded in `Logs/Hist/` —
which, per the `"a"` ad hoc discovery, is now most usage. Group-level
protection remains the fallback for the residual case (activity found
only in `Logs/Report/`, never in `Logs/Hist/`, still owner-blind): if
any template sharing a key is active, all of them are treated as active.
That's a false-negative bias, not a false-positive one — a genuinely-dead
template sharing a key with an active sibling stays protected too,
matching this tool's existing conservative posture (quarantine over
delete, erring toward keeping things).

No template-renaming operational rollout is needed to get this
protection — it's available immediately from log history already on
disk.

## New candidate selection logic

Replaces the original spec's step 2 (`last_run`/`created` inactivity
rule) entirely. Steps 1 (`frequency_flag == "n"`) and 3 (owner exclusion)
are unchanged.

1. Build a merged activity index once per run (cached and updated
   incrementally, not rebuilt from scratch every time — see
   Implementation notes):
   - Parse `Logs/Report/*.log` and `*.log.Z` for `Finished report` lines
     → `(report_type, description) → most recent timestamp`.
   - Parse `Logs/Hist/*.hist` and `*.hist.Z`, pre-filtered by raw command
     code, decoded only for the matched subset → `(report_type,
     description, owner) → most recent timestamp` for `ge`/`gk` events
     specifically (the ones that represent real usage, not just
     schedule bookkeeping).
   - Only the last `--years` (default 3) of both sources needs scanning
     — not full retention. This is what keeps the `Logs/Hist/`
     performance cost tractable despite its 12+ year retention.
2. For each manual template row, look up its `(report_type,
   description[, owner])` in the merged index:
   - Found in **either** source, within `--years` of today → **not** a
     candidate (active). Two independent sources checked, active in
     either wins — deliberate defense in depth given this exact category
     already caused a production incident under a single, wrong signal.
   - Not found in either, or found only outside the window → candidate,
     *unless* `created` is more recent than `--years` ago (a template
     that's simply new shouldn't be flagged just because it hasn't run
     yet — matches the original rule's never-run-yet handling, and
     `created` is still trustworthy for this narrow purpose on `"n"`
     rows specifically).
3. Owner exclusion: unchanged (`--exclude-owner` / `--exclude-owner-regex`).

`--years` keeps its default of `3`. This is direct evidence of
execution, not a proxy, so the original calibration stands.

## Implementation notes

- **`.Z` decompression**: Python's stdlib `gzip` module cannot read Unix
  `compress` (`.Z`) format. Shell out to `zcat` via `subprocess`
  (confirmed present on the production box; still stdlib-only per the
  project's Python 3.6.8 constraint, since this uses an existing system
  utility, not a pip package).
- **Read-only discipline**: the entire log-reading phase has zero write
  access to anything under `Logs/` — no in-place decompression, no temp
  files written alongside source logs, `zcat`/`logprint`/`translate`
  used purely as read pipes. Any derived state (the activity-index
  cache) lives in a file this tool owns, under `--quarantine-dir` by
  default, never near `Logs/`.
- **Module layout** (`rptsched_lib/`):
  - `report_log.py` — `Logs/Report/` parsing. Plain text, no subprocess
    beyond `zcat` for `.Z` months.
  - `hist_log.py` — `Logs/Hist/` parsing: raw code pre-filter, `zcat`
    for `.Z`, `logprint | translate` subprocess pipe for the matched
    subset, field extraction. Owns the incremental cache for this source
    specifically, since it's the one actually worth caching.
  - `activity_index.py` — merges both sources into one lookup ("is
    `(report_type, description[, owner])` active within N years"),
    persists the combined cache. `templates.py` depends on this
    interface only, not on log-parsing internals — keeps it reusable for
    the still-parked scheduled-report-removal category later.
  - `templates.py` (existing) — candidate selection swaps its
    `last_run`/`created` check for an `activity_index` lookup; owner
    exclusion and the `created`-recency floor stay as they are.
  - `quarantine.py` / `schedlist.py` (existing) — execute/restore
    mechanics unchanged by this redesign.
- New CLI flags on `remove_stale_templates.py`, following the existing
  "never hardcoded" convention: `--logs-report-dir`, `--logs-hist-dir`
  (both required, no built-in defaults, same as `--data-dir`), and
  `--index-cache-path` (optional, defaults under `--quarantine-dir`).

## Explicitly out of scope (unchanged from original spec)

- Scheduled report removal candidates (recurring + inactive) — still a
  separate script/spec, still parked.
- Orphans — separate script/spec, already written, untouched by this
  redesign.
- Concurrency/locking against Symphony's own processes reading/writing
  `schedlist`, `Logs/Report/`, or `Logs/Hist/` — still out of scope;
  atomic rename remains the only safety mechanism specified, and the log
  sources are read-only inputs regardless.
