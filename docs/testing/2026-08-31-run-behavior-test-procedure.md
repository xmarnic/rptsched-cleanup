# Report-run behavior test procedure

## Why this exists

Production tickets reported templates removed by `remove_stale_templates.py`
that were, per the reporting staff, still in heavier use than the
`last_run`-based inactivity rule assumed. A first round of test-server
experimentation (`z-schedlist-test.tar.gz`, run against `NATRBIBMGR`'s
`qmod`/TS2orderload and `efwj`/TS2bibload templates) found that the
`schedlist`/`.set`/`.selans` data model doesn't behave the way
`rptsched-domain-reference.md` currently describes it. This procedure exists
to pin down exactly how it behaves, with controlled single-variable trials,
before we revise the domain reference or change cleanup logic.

**Golden rule: one UI action per trial.** The first round combined two
templates across two loosely-defined rounds, and the result (0 changes in
round 1, 2 new rows in round 2, against an expectation of 4) can't be
cleanly attributed to a specific action. Every trial below isolates exactly
one action so its effect is unambiguous.

## What we already know (round 1 findings)

- Running `qmod`/`efwj` **never** updates the original template's
  `schedlist` line, `.set`, or `.selans` — confirmed byte-identical
  (sha256) across `pretest` → `posttest-1` → `posttest-2`.
- Between `posttest-1` and `posttest-2`, two brand-new `schedlist` rows
  appeared: `jiem` (TS2orderload) and `jien` (TS2bibload), both owned by
  `NATRBIBMGR`, both `frequency_flag = "o"` — a value **not documented
  anywhere in `rptsched-domain-reference.md`** (which only lists `n` and
  `d1`/`w1`-`w7`/`m1`-`m31`).
- `pretest` → `posttest-1` was **byte-identical** — the action taken in
  that round left zero trace anywhere in the directory. This is the most
  important open question: if a real "run" can leave literally no trace,
  no metadata-based signal (however well designed) can detect it.
- `"o"` isn't new to this test — the fuller `rptsched/` production mirror
  already has 8 pre-existing `"o"` rows, all owned by `SIRSI` (a system
  account), all `unauth`/`unauthload` (Authority Update Export/Load), all
  with **future-dated** `created` timestamps spaced ~quarterly, all
  `last_run = 0000000000`. Working hypothesis: `"o"` rows are queued
  one-time jobs, not persistent templates.
- Production also has an undocumented `"p<N>"` frequency family (`p92`,
  `p365`, `p14`, `p2`, ...) — presumably "every N days" — never mentioned
  in the domain reference either.
- **Confirmed (not a hypothesis — user directly scheduled this on the test
  server):** `frequency_flag = "o"` means **"run once"** — a genuine
  one-time-scheduling option in Setup and Schedule, distinct from saving a
  recurring schedule. Scheduling a one-time run creates a brand-new
  `schedlist` row (fresh ID, `frequency_flag = "o"`, `created` = the
  scheduled fire time) rather than touching the original template. This
  is *not* a double-click/copy side effect — that earlier read of round 1
  vs round 2 was wrong. It cleanly explains the future-dated `created` on
  `jiem`/`jien` and on the pre-existing `SIRSI` `"o"` rows in
  production: those are one-time runs scheduled for a future date that
  simply hadn't fired yet when we snapshotted.
- Still open: what exactly produced round 1's zero-trace result
  (`pretest` → `posttest-1`, byte-identical). Since "o" is now explained
  by run-once scheduling rather than double-click, Trial 1 below still
  needs to confirm what **Setup and Schedule → Run Now** (immediate, not
  scheduled) actually does — that's the one action from round 1 we still
  don't have a confirmed explanation for.

## Ground rules for every trial

1. **One action per trial.** Never combine two UI paths, or two templates,
   in the same before/after snapshot window.
2. **Snapshot the whole `schedlist`**, not a grep'd subset — new rows land
   under IDs you can't predict in advance. Diff the full file every time.
3. **Snapshot before and immediately after** each action. Also snapshot
   again after a delay (see Trial 5) where the trial calls for it.
4. **Use a fresh, never-before-tested template ID** for each new variant
   under test, so results aren't contaminated by a prior trial's leftover
   `"o"` rows or state.
5. **Record wall-clock start/end time** of the action and which staff
   account performed it, so timestamps found afterward can be correlated
   back to a specific trial.
6. **Copy snapshots back with `tar`**, not a plain file copy — mtimes are
   the signal, and tar is the one method here that bakes them into the
   archive regardless of how the tarball itself gets moved around
   afterward.
7. For each companion file present, record `mtime`, `size`, and `sha256` —
   not just mtime — so a same-second rewrite with unchanged content isn't
   mistaken for "no change" or vice versa.
8. Note anything Symphony shows on-screen (success message, printed
   output, error) — if a trial leaves zero trace on disk, the on-screen
   behavior is the only way to confirm the report actually ran at all.

## Trials

### Trial 1 — Setup and Schedule → Run Now, no double-click, repeat for confirmation — CONFIRMED

Run against `weql` (`TS2orderload`, `SHRCWSL`, never-run — same profile as
`qmod`). Two sub-variants tested, both immediate (not scheduled) runs:
**Setup and Schedule → Run Now**, and **double-click → Run Now**.

**Result: zero changes, for both.** `schedlist` and `weql.selans`/
`weql.set` are byte-identical (sha256 match) across `0-pretest` →
`1-posttest` (Setup and Schedule) → `2-posttest` (double-click). No new
rows, no changed `last_run`, no changed file content.

Combined with the confirmed `"o"` = "run once" finding above, this gives
a clean, three-way-tested conclusion: `schedlist`/`last_run`/`.selans`
only get touched by Symphony's scheduling engine (a recurring schedule
firing, or a "run once" job firing at its scheduled time). An immediate,
ad hoc "Run Now" — via either menu path — never touches persisted state
at all. This isn't an unreliable signal for that usage pattern; there is
**no signal, structurally**, for it. Trials 2-5 (below) still stand for
mapping the "run once" ("o") behavior in more depth, but the original
"is ad hoc Run Now detectable at all" question is answered: no.

### Trial 2 — Schedule a one-time run ("Run Once")

Same template family, fresh ID. Use Symphony's "run once" scheduling
option (not an immediate Run Now). Snapshot before/after.

Confirmed already (this is what the user directly observed on the test
server, not just an inference from round 2): a new `"o"`-flagged row
appears with a fresh ID and a `created` timestamp matching the scheduled
fire time; the original template's line/files are untouched. This trial
now mainly exists to nail down timing precision (does `created` match the
scheduled time exactly, or the time it was *set up*?) rather than to
re-confirm the row appears at all.

### Trial 3 — Repeat Trial 2 on a non-batch-load report type

Pick a template whose `report_type` is *not* `TS2bibload`/`TS2orderload`
(e.g., an `itemlist` or `bibliography` template). Schedule a one-time run
on it. Determines whether "run once" spawning a new `"o"` row is general
to all report types, or specific to the batch-load family — this matters
for how broadly any resulting cleanup-logic change should apply.

### Trial 4 — Schedule a one-time run on the same template twice, separate sessions

Schedule a one-time run on the *same* template a second time (different
session, ideally different day). Does it spawn a **second** new `"o"`
row, or update the first one (`jiem`/`jien`-equivalent) in place?
Determines whether `"o"` rows accumulate unboundedly (one per scheduled
run) or get reused — relevant to whether they're ever a cleanup target
themselves.

### Trial 5 — Does an `"o"` row's own `last_run` ever update?

After Trial 2 or 4 creates a new `"o"` row, do nothing further to it, but
re-snapshot at two points: (a) shortly after creation, (b) after the
row's own `created` timestamp has passed (recall: `jiem`/`jien`'s
`created` was ~11 days in the future relative to when the action was
taken). If `created` really represents a scheduled future fire time, this
tests whether the row updates its own `last_run` when that time arrives,
or whether it too stays frozen at `0000000000` forever — which would mean
`"o"` rows are single-use and never look "active" by the existing
inactivity rule after the fact, no matter when you check.

### Trial 6 — Identify the actual mechanism behind the 2025-07-01 batch cluster

Out of scope for GUI-only testing: ~40 `TS2bibload` templates across many
different owners had their `.selans` rewritten within the same ~30-minute
window in production. That's very unlikely to be manual double-click
activity — it's more consistent with a scheduled batch/EDI import process
running outside the interactive scheduler entirely. Follow up with
whoever owns that batch job (if known) rather than trying to reproduce it
via the GUI — knowing whether it goes through `schedlist` at all, or
updates a different template than the one a human would recognize, is
important context for whether the pattern found in Trials 1-5 explains
this cluster too.

## What this means for cleanup logic, regardless of trial outcomes

- **Primary signal stays `.selans` mtime cross-checked against
  `schedlist`'s `last_run`** — but disagreement between them should now
  be treated as informative on its own (flag for review) rather than
  picking one to trust blindly, since we've already shown they can
  diverge (`fsxk`/`ftcb`/`gbhx` in the original NATRBIBMGR review, and now
  `qmod`/`efwj` never updating at all despite real runs).
- **The unit of "is this in use" may not be a single `schedlist` row.**
  If real usage of a report family shows up as new `"o"`-flagged rows
  under fresh IDs rather than updates to a long-lived template, then
  evaluating `qmod`/`efwj` in isolation is the wrong question — the right
  question is whether *any* row sharing the same `report_type`/`owner`/
  `description` cluster shows recent activity.
- **Confirmed (Trial 1): a genuine no-trace action exists.** Ad hoc "Run
  Now" — the ordinary way staff would actually use a saved template day
  to day — leaves nothing anywhere in `rptsched/` to find, by any
  metadata-based method. No amount of refining the signal (which file,
  which field, which threshold) closes this gap, because there's nothing
  to detect. The honest mitigation is the same one already used for ACQ:
  exclude known-risky `report_type`/owner combinations from automated
  removal via `--exclude-owner-regex` (or a new `--exclude-report-type`
  if this turns out to be common), rather than trying to perfect
  detection for a case that structurally can't be detected. This is
  likely the real, confirmed explanation for the production tickets:
  `efwj`/`qmod` may well have been run regularly by hand, and the
  inactivity rule was blind to it by design of how Symphony persists (or
  doesn't) that action — not because of a threshold or signal bug in the
  cleanup script itself.
