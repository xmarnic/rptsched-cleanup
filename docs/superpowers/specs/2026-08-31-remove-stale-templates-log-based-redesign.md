# remove_stale_templates — Redesign: log-based detection

## Status

Supersedes the candidate-selection logic in
`2026-07-24-remove-stale-templates-design.md` (still the reference for
everything about modes, quarantine/manifest/restore mechanics, and CLI
shape — none of that changes here). This document covers **only** what
counts as a removal candidate and why the original rule doesn't work.

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
original rule needed.

## The real signal: `Logs/Report/`

`/software/WYLD/Unicorn/Logs/Report/` contains a system-wide execution
log, independent of `schedlist` entirely:

- Current month uncompressed (`YYYYMM.log`) plus a same-day daily file
  (`YYYYMMDD.log`); prior months compressed (`YYYYMM.log.Z`, Unix
  `compress` format — not gzip). Confirmed present back to at least
  **January 2021** (5+ years of retained history as of this writing).
- Every report execution — ad hoc or scheduled, no exceptions found in
  testing — produces a line:
  ```
  YYYYMMDDHHMMSS Starting report <report_type>:"<description>"
  YYYYMMDDHHMMSS Adding report <report_type>:<description> to finished list
  YYYYMMDDHHMMSS Finished report <report_type>:"<description>"
  ```
  Confirmed format-stable from August 2025 through today; confirmed to
  record every action type tested (immediate run via both UI paths, ASAP,
  run-once, and actual recurring-schedule fires).
- When a report is configured to auto-mail its output, the log also
  captures sender/recipient email:
  `Automatically mailing report <type>:"<desc>" from <sender> to <recipient>`
  — a secondary cross-reference when it's present (some `schedlist` rows
  carry an email address in their own fields), but not universal.

**This is the real usage signal** — it exists for exactly the usage
pattern (`schedlist` `last_run`) that turned out to be blind.

## The join-key limitation, and why it's survivable

Log entries identify a run by `(report_type, description)` — there is no
per-run id, username, or session field bracketing these lines (checked
directly; not present in the sampled context around several entries,
including our own test runs).

Checked against the local `rptsched/` mirror (5,311 rows, 4,053 manual):
**3,443 of 4,053 manual templates (85%) have a `(report_type,
description)` pair unique to them** — the log joins back to exactly one
`schedlist` row for those. The remaining **610 templates across 220
shared pairs (15%)** are ambiguous, concentrated almost entirely in
templates that never got a custom description (literally the
`report_type` repeated as `description`, e.g. bare `"TS2bibload"`, or an
unedited message-catalog default like `$<list_items>`). Notably, `efwj`
and `qmod` — the two templates that surfaced this whole investigation —
are themselves in the ambiguous 15% (`"TS2bibload"`/`"TS2orderload"` bare
descriptions are shared by 13 and 18 templates respectively, across 11
and 17 owners).

The ambiguity is survivable because **the join key itself provides
group-level protection for free**: since every template sharing a
`(report_type, description)` pair produces the same lookup result, "is
this key active" and "is this specific template active" collapse to the
same question for ambiguous groups. The cost is symmetric with the
benefit — a genuinely-dead template sharing a key with an active sibling
stays protected too (a false negative, not a false positive). That's the
correct failure direction for this tool: it already treats quarantine
as reversible and erring toward keeping things over removing them
correctly, and this is the same bias applied one level up.

## New candidate selection logic

Replaces the original spec's step 2 (`last_run`/`created` inactivity
rule) entirely. Steps 1 (`frequency_flag == "n"`) and 3 (owner exclusion)
are unchanged.

1. Build a last-activity index once per run: parse `Logs/Report/*.log`
   and `Logs/Report/*.log.Z` for `Finished report` lines, extract
   `(report_type, description) → most recent timestamp`.
2. For each manual template row, look up its `(report_type, description)`
   in the index:
   - Found, timestamp within `--years` of today → **not** a candidate
     (active).
   - Found, but older than `--years` → candidate (same as never-found,
     below), *unless* `created` is more recent than `--years` ago (a
     template that's simply new shouldn't be flagged just because it
     hasn't run yet — matches the spirit of the original rule's
     never-run-yet handling).
   - Never found anywhere in retained log history → candidate, subject
     to the same `created`-recency floor above. (For a template created
     before log retention begins, "never found" means "hasn't run in at
     least the full retained window" — 5+ years currently — which is
     itself stronger evidence than the `--years` default requires.)
3. Owner exclusion: unchanged (`--exclude-owner` / `--exclude-owner-regex`).

`--years` keeps its default of `3`. The original concern about widening
it (weaker signal deserves a more conservative threshold) doesn't apply
here — this is direct evidence of execution, not a proxy, so the
original calibration stands.

## Implementation notes

- **`.Z` decompression**: Python's stdlib `gzip` module cannot read Unix
  `compress` (`.Z`) format — it's LZW-based, unrelated to DEFLATE. The
  box has a working `zcat` (confirmed interactively). Shell out to it via
  `subprocess` (still stdlib-only per the project's Python 3.6.8
  constraint — this uses an existing system utility, not a pip package).
- **Performance**: parsing 5+ years of monthly logs on every invocation
  will be slow and grows monthly. Worth caching the built index (e.g. to
  a local file keyed by which log files have already been folded in) and
  only parsing new/changed log files on subsequent runs, rather than a
  full rebuild each time. Not spec'd in detail here — flagging as a
  needed design decision before implementation, not a blocker to this
  redesign's correctness.
- New internal module (e.g. `rptsched_lib/report_logs.py`) owns log
  location/parsing/indexing; `templates.py`'s candidate selection
  consumes the index instead of reading `last_run`/`created` for the
  inactivity check.

## Operational rollout (matches the plan already in motion)

1. **Clean out what we can now.** The 85% unambiguous case already has
   5+ years of usable log history — run the new detection logic and
   execute against genuine candidates immediately, same quarantine/
   restore mechanics as before (unchanged by this redesign).
2. **Disambiguate the 15%.** Rename manual templates whose description
   collides with other owners' (the 220 shared pairs) to include a
   library/owner prefix, via Symphony's normal template-edit UI — already
   the convention most WYLD sites follow (`"SHER TS2bibload"`, `"ALBY
   TS2bibload"`, etc.); it's specifically the un-prefixed generic ones
   that collide.
3. **Observe before trusting a rename.** Renaming only disambiguates
   *future* log entries — historical lines under the old shared
   description don't retroactively attach to the new name. A one-month
   observation window (as planned) is enough to catch renewed activity
   under the new name (if it runs, it's obviously protected), but **is
   not enough on its own to conclude a freshly-renamed template is
   stale** — absence of activity in one month is weak evidence against a
   3-year threshold. During the transition, keep using the old shared
   key's activity as the operative signal for a freshly-renamed
   template's group; only let a renamed row be judged independently once
   it's accumulated close to a full `--years` window of its own history
   under the new name.

## Explicitly out of scope (unchanged from original spec)

- Scheduled report removal candidates (recurring + inactive) — still a
  separate script/spec, still parked.
- Orphans — separate script/spec, already written, untouched by this
  redesign.
- Concurrency/locking against Symphony's own processes reading/writing
  `schedlist` or `Logs/Report/` — still out of scope; atomic rename
  remains the only safety mechanism specified.
