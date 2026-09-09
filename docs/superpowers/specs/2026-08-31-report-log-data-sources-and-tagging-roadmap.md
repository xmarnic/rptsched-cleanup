# Server-side data sources beyond rptsched/ — what we know, what tagging could add

## Purpose

Companion to `2026-08-31-remove-stale-templates-log-based-redesign.md`
(now partially superseded by this document — see "The finalized
empirical method" below). This document is the broader inventory —
every data source found outside `rptsched/` during that investigation,
what's confirmed, the finalized detection method, what tagging can still
add on top of it, an assumption worth flagging explicitly, and what's
achievable today vs. only after time passes.

## Data source inventory

### `Logs/Report/*.log` / `*.log.Z` — confirmed, in active use

Path: `/software/WYLD/Unicorn/Logs/Report/`. Monthly rotation
(`YYYYMM.log`, compressed to `YYYYMM.log.Z` after the month closes — Unix
`compress` format, not gzip), plus a same-day daily file
(`YYYYMMDDHHMMSS`-stamped lines within `YYYYMMDD.log`). Confirmed present
back to **January 2021** (5+ years retained as of 2026-08-31).

Confirmed format, stable from at least August 2025 through today:
```
YYYYMMDDHHMMSS Starting report <report_source>:"<description>"
YYYYMMDDHHMMSS Adding report <report_source>:<description> to finished list
YYYYMMDDHHMMSS Finished report <report_source>:"<description>"
```
Plus, when a report auto-mails its output:
```
YYYYMMDDHHMMSS Automatically mailing report <type>:"<desc>" from <sender> to <recipient>
```
And scheduler-internal lines, e.g. `Reportcron: ASAP request` (the
polling daemon picking up queued ASAP jobs).

Confirmed via direct testing to record **every** execution type we tried
— ad hoc Run Now (both UI paths), Schedule→ASAP, Schedule→Once, and
actual recurring-schedule fires — with no exceptions found. This is the
one data source proven to close the gap left by `schedlist`'s `last_run`.

**Known limitation**: keyed by `(report_source, description)`, no
per-entry id/user/session field. See the redesign spec for the
85%/15% unambiguous/ambiguous breakdown this produces.

**Volume**: confirmed via direct count — ~160,707 lines for January 2021
alone, ~73,635 lines so far for August 2026 (partial month). Roughly
100K-160K lines/month × ~68 months retained is several million lines
total. Confirms the caching/incremental-parsing concern in the redesign
spec is a real requirement, not a hypothetical nice-to-have — a full
re-parse of the entire history on every run, including `.Z` decompression
across 60+ historical files, would be genuinely slow.

**Two additional findings from sampling old data (January 2021), both
tangential to this redesign but worth recording:**

- **"Missing parameter file" lines reveal broken recurring schedules.**
  Format: `Missing parameter file for <description>:"<id>"` — includes
  the actual `schedlist` id directly. Repeats roughly every 5 minutes,
  indefinitely (13,680 occurrences in one month for a single id) — this
  is Reportcron attempting to fire a *recurring* schedule whose `.set`
  file no longer exists on disk, failing silently, forever. A distinct
  data-integrity problem from stale manual templates: a live schedule
  entry pointing at a file that's already gone. Worth its own
  investigation as a possible future cleanup category — not scoped here.
- **Real malformed `schedlist` lines exist, and they'd affect our own
  parsing too.** `Maximum schedlist field length exceeded; cannot parse:
  "lodi|itemlist|LINC_STAR - lost | lost assumed | lost claimed | lost
  paid|n|202101201416|0000000000|STARILL||||||0|3||0|||"` — that
  description contains literal unescaped `|` characters, which breaks
  pipe-delimited parsing generally, including Symphony's own reportcron
  (this message is it failing) and, unverified but structurally certain,
  `rptsched_lib/templates.py`'s `raw_line.split("|")`. For the current
  stale-templates candidate logic specifically, the failure mode is safe
  — a garbled `frequency_flag` from the shifted fields just never equals
  `"n"`, so the row is silently skipped rather than wrongly acted on —
  but it's a real robustness gap worth fixing at some point: validate
  field count or bound the split rather than trusting every line has the
  expected shape.

### `Rptprint/` — characterized

Path: `/software/WYLD/Unicorn/Rptprint/`. Per-execution files named by a
short id distinct from the `schedlist` id — a fresh id is minted per
actual print/report job, not reused from the template (e.g. `kdlu`'s
weekly fire, a `schedlist` row, showed up here as job id `gzjw`). Each
job gets an `<id>.log` (execution record — report source, description,
precise timestamp, and for at least one report source, the underlying SQL
and row counts) and an `<id>.prn` (print-ready rendered output — empty
for jobs with no configured print/notice delivery, as expected; not
useful for detection). There are also `rpt<letter><random>`-named files
(e.g. `rptlJOUeQ`) and a `shadowed.txt`, purpose not yet examined —
lower priority, likely in-flight job temp files.

The real find is **`printlist`**, a flat pipe-delimited index — one line
per job:
```
id|description|timestamp|status|owner|report_source|0|||
gdvo|COKE List Users with Bills|202608170534|OK|COKEILL|billuser|0|||
```
**Confirmed the `owner` field is the real template owner** — all six of
our own test jobs show `owner=NMARLIN`, matching `kdkx`'s actual
`schedlist` owner exactly. That means `printlist` supports joining on
`(report_source, description, owner)` — a combination that resolves
almost all of the ambiguous cases `Logs/Report/` can't (most of the 220
shared-description groups are one-template-per-*different*-owner, which
owner alone disambiguates).

**But retention is short**: confirmed via `head`/`tail`/`wc -l` —
7,471 lines spanning only **2026-08-17 to 2026-08-31** (~2 weeks), a
small fraction of `Logs/Report/`'s 5+ years. This reads as a rolling
job-queue/print-delivery backlog that gets pruned once processed, not a
long-term audit log. We did not confirm whether an archived/rotated
history exists elsewhere (not checked before moving on) — worth a
follow-up `find` for a `printlist`-adjacent archive if this becomes
important later, but treat "no archive" as the working assumption for
now.

**Practical implication**: `printlist` can't replace `Logs/Report/` as
the primary 3-year signal — too short-lived — but it's a much cleaner
*disambiguator* than anything else found. The actionable move: **start
archiving `printlist` going forward** (a small periodic job appending new
rows to our own persistent copy before they roll off the ~2-week window),
so from today onward we accumulate real, zero-ambiguity
`(report_source, description, owner)` history — while still relying on
`Logs/Report/`'s existing 5 years for anything historical. This is a
"today" action (cheap, additive, doesn't touch any live template) worth
doing well before the id-tagging feature is built, since every day not
archived is history we can't get back later.

### `Logs/Hist/*.hist` / `*.hist.Z` — characterized

Path: `/software/WYLD/Unicorn/Logs/Hist/`. Monthly rotation like
`Logs/Report/`, but retained even longer — confirmed present back to at
least **June 2014** (12+ years as of 2026-08-31). This is Symphony's
general transaction history log, not report-specific — it mixes in every
other transaction type (circulation, patron edits, item edits,
acquisitions, everything), so scope discipline matters when parsing it.

**Decoding**: raw records are caret-delimited field codes, not plain
text. Symphony ships its own decoder — `logprint | translate` — which
turns a raw line into a fully labeled, human-readable transaction. Use
it via `subprocess` (external system utility, still consistent with the
project's stdlib-only constraint, same as the `zcat` approach for
`Logs/Report/`'s `.log.Z` files). Confirmed field mapping from direct
correlation against our own test actions:

| Raw code | Decoded meaning |
|---|---|
| `^oa` | schedule id (the `schedlist` id) |
| `^ob` | report_source ("name of run script") |
| `^oc` | description ("scheduled report name") |
| `^od` | frequency |
| `^oe` | next-scheduled-run date |
| `^of` | last-run date (`NEVER` = the `0000000000` sentinel) |
| `^FW` | acting user (`station user's user ID`) |
| `^FD` | station type (`PCGUI-DISP` = interactive GUI client) |

**Full command vocabulary**, surveyed against one real production day
(2026-08-31) by decoding only lines containing `schedule id:`:

| Command | Count | What it means for detection |
|---|---:|---|
| `Set Report Options` | 778 | Per-tab dialog navigation noise (title/footer/seluser/... as a user clicks through the setup screen). Not useful alone. |
| `Search Order Part B` | 139 | **False positive** — an unrelated acquisitions/order-search command that happens to reuse the literal `"schedule id:"` field label. Any implementation must filter by known command name, not just co-occurring text, or it pulls in ACQ noise. |
| `Create Scheduled Report` | 69 | The commit/save event. Carries frequency, owner, id, report_source, description — including the newly-discovered **`frequency:"a"` = ad hoc**, confirmed via our own test (`kdlg`/`kdll`/`kdln`/`kdlv`, one spawned per ad hoc action). This never persists to `schedlist` at all, but *is* logged here with full attribution — the direct answer to "can we detect ad hoc Run Now," which no `rptsched/`-internal signal could. |
| `Remove Finished Report` | 60 | Fires when a user dismisses a completed report from their Finished Reports list. Carries `schedule id`, report_source, description, and **`login of the owner of the report`** (the authoritative owner field, distinct from the acting user in `^FW`). Strong positive evidence of a genuinely completed+reviewed execution — but conditional: auto-delivered reports may never generate this event, so its *absence* proves nothing. A corroborator layered on `Logs/Report/`'s unconditional `Finished report` line, not a replacement for it. |
| `Rename Scheduled Report` | 11 | Editing an *already-scheduled* entry; carries an `oS:<old_id>` field linking to what it replaced (e.g. a real production example: `oS:gqwq` → `kdqb`). **Correction to an earlier hypothesis from mid-investigation**: this link only appears on `Rename`, connecting a schedule to its own previous generation — it does **not** appear on fresh `Create Scheduled Report`, so it does not link a spawned schedule back to the original manual template that configured it. Description/report_source(+owner) matching is still required for that connection. |
| `Remove Scheduled Report` | 9 | Deletion of a schedule entry. Simple — just the id. |
| `Modify Scheduled Report` | 5 | Confirms `suspend status:Y` is real and logged — directly relevant to (though out of scope for) the still-parked scheduled-report-removal category in `rptsched-domain-reference.md`. Also shows ownership reassignment via the same `login of the owner of the report` field. |
| `Process Answers File` | 1 | Too rare in this sample to characterize; not investigated further. |

**Performance strategy — pre-filter before decoding.** `logprint |
translate` is a full-fidelity decoder but expensive to run over an
entire file that's mostly unrelated transaction types. The fix: grep the
**raw** file for a marker unique to report-schedule transactions (`^oa`
is present on every report-related line we've checked; the unrelated
circulation/patron transaction types use entirely different field codes)
before ever decoding, so only the report-related fraction gets the
expensive treatment:
```
zcat 202101.hist.Z | rg -F "^oa" | logprint | translate
```
**Reduction magnitude confirmed with real data**: measured directly
against 31 of the 3 years of `.hist.Z` files now held locally in
`logs/Hist/` (a fresh pull from production) — 56.7M raw lines total,
987,198 matching `^oa`, a consistent **1.74% ratio (~57.5x fewer lines
to decode)** across every sampled month (range roughly 1.4%-2.1%,
month to month). This is a real, substantial win for the pre-filter
strategy, not a hypothetical one.

**`^S<seq><flag>` command-code hypothesis — confirmed.** Every raw line
carries its command as a 2-character code directly after the `^S<seq>`
sequence number (e.g. `^S93goFF17TECH...`). Checked against a published
TRG command-code table and verified directly against real raw data —
`logs/Hist/20260831.hist`, the current day's file, already held locally
as part of the 3-year pull, so this needed no server round-trip at all:

| code | table says | raw count (this file) | decoded count (same file, earlier survey) |
|---|---|---:|---:|
| `ge` | Create Scheduled Report | 72 | 69 |
| `gg` | Modify Scheduled Report | 5 | 5 |
| `gh` | Remove Scheduled Report | 9 | 9 |
| `gk` | Remove Finished Report | 62 | 60 |
| `go` | Set Report Options | 963 | 778 |
| `gu` | Rename Scheduled Report | 11 | 11 |

`ZC` (table: Print Report) was also checked — zero occurrences in this
file. Not pursued further: Print Report isn't part of the signal this
tool needs (dialog/output noise, same category as `go`), so whether the
code guess is right is irrelevant to detection.

`gg`/`gh`/`gu` match exactly; `ge`/`gk`/`go`'s drift (+3, +2, +185) is all
the same cause — the raw grep was taken slightly later than the decoded
survey, against the same file, on a live production server that kept
generating transactions in between. `go` just has a high enough baseline
rate (963 in one day) that the same time gap produces a bigger absolute
drift than it does on the low-volume codes. Closed — not a detection
gap, and `go` is excluded noise regardless.

Practical payoff: classification by command type no longer requires
`logprint | translate` at all — `\^S[0-9]+g[ehgku]` (or one alternation
per wanted code) identifies the exact commands we care about (Create /
Modify / Remove Scheduled / Remove Finished / Rename) directly in raw text, and
is *more* precise than the `^oa` pre-filter below, since it can't pick
up `Search Order Part B`'s raw lines the way a marker shared across
command types can. Decoding (`logprint | translate`) is still needed
after this filter, but only to extract field *values* (id, report_source,
description, owner) from the already-classified subset — not to decide
which lines matter in the first place.

**Closed.** The raw command format (`^S<seq><code>` — fixed-width fields,
a stable Symphony-internal transaction log structure, not something that
drifts month to month) is the same mechanism across the whole 3-year
window; one day's file exercising 6 of the codes with near-exact counts
is representative of the format, not a fluke specific to today. No
further per-month spot-checking needed before implementation.

### `schedlist` + `.set`/`.selans` — already fully covered

See `rptsched-domain-reference.md` (schedlist format, inactivity rule,
trustworthy vs. untrustworthy mtimes) and the log-based redesign spec
(why `last_run` doesn't work for manual templates). Nothing new to add
here beyond what's already documented.

## The join-key problem is mostly already solved, without tagging

Earlier framing in this doc treated id-tagging as *the* fix for the 15%
ambiguous case found in `Logs/Report/` alone. That's now superseded:
`Logs/Hist/`'s `login of the owner of the report` field (on `Create`,
`Rename`, and `Remove Finished Report` events) means
`(report_source, description, owner)` is achievable **today**, using
history that already exists going back over a decade — no renaming
campaign required first. Owner alone resolves nearly all of the 220
shared-description groups, since the dominant real-world case is one
template per *different* owner sharing a bare description (e.g. 17
distinct owners sharing bare `"TS2orderload"`).

Tagging isn't pointless, just demoted from "the fix" to "closes a
residual edge case": nothing stops two templates under the *same* owner
from sharing an identical description too, though we haven't observed
that happening. The rest of this section still applies to that narrower
case.

You asked specifically what embedding an identifier and/or library code
into a template's `description` would accomplish. Two distinct versions,
worth keeping separate:

**Library/owner prefix** (what's already partially in use, e.g. `"SHER
TS2bibload"`, `"ALBY TS2bibload"`) — reduces cross-owner collisions,
which is the dominant real-world case (11-17 distinct owners sharing a
bare `"TS2bibload"`/`"TS2orderload"` description). Doesn't guarantee
uniqueness — nothing stops two different templates under the *same*
owner from ending up with the same prefixed description, though we found
no evidence of that happening in practice.

**Embedding the template's own 4-character `schedlist` id** (a new idea,
stronger than the prefix alone) — e.g. `"[efwj] TS2bibload"` instead of
`"SHER TS2bibload"` or bare `"TS2bibload"`. This is a *complete* fix, not
a reduction: the id is guaranteed unique and permanent for that row's
lifetime (per the domain reference, it's "the join key across all of
this"). Once tagged, every future `Logs/Report/` line for that template
carries its own id inside the description text — a parser can extract
the id via a simple pattern match and get a perfect join, regardless of
how many other templates share the same `report_source` or the rest of the
description. This closes the ambiguity gap to zero, not just to 85%.

Combining both (id **and** owner/library code) is reasonable — the id
for machine-parseable certainty, the owner code for a human glancing at
the report list to still recognize what it's for.

**What this can't do**: identify *who* ran the report on a given
occasion, beyond what's already available without tagging at all.
`Logs/Report/` has no session/user field, and tagging the description
doesn't create one there — but `Logs/Hist/` already carries the acting
user (`^FW`, "station user's user ID") on every event, and the
authoritative template owner (`login of the owner of the report`) on
`Create`/`Rename`/`Remove Finished Report` specifically, independent of
whether the description is tagged. Tagging only makes the *template*
itself more reliably identifiable by text pattern; it doesn't add
attribution that `Logs/Hist/` doesn't already provide.

## An assumption worth flagging explicitly

The whole log-based redesign — as spec'd — assumes a template's
`description` stays constant over its lifetime once we start indexing
off it. That's not actually guaranteed: staff can rename a template's
description at any time, for reasons unrelated to this project. If that
happens, historical entries (in either `Logs/Report/` or `Logs/Hist/`)
under the *old* description become orphaned from the row's *current*
description going forward — the new detection logic could see "no
activity" for a template that's actually still running regularly, just
logged under text that no longer matches, and wrongly flag it stale.
This is a real risk the original `last_run`-based rule didn't have (it
was tied to the row directly, not to text that can drift).

This is the strongest argument for the id-tagging idea above, not just
the owner-prefix version: if the parser keys off the **id substring**
within the description (via a pattern match) rather than the full
literal description string, an unrelated future edit to the surrounding
text doesn't break the join — only removing the id substring itself
would, which is a much narrower failure mode and one staff could be
asked to simply never do (e.g. "don't delete the `[xxxx]` tag when
editing a report name").

## The finalized empirical method

Pulling everything above into one concrete algorithm:

1. Start with every `schedlist` row where `frequency_flag == "n"`,
   flagged as a removal candidate by default.
2. Scan only the last `--years` (3, the existing default) of log
   history — deliberately **not** the full retention depth (5-12 years).
   Bounding the window to what the rule actually needs is what makes the
   `Logs/Hist/` performance question tractable at all; nothing here
   requires processing more than 36 months of either log.
3. Within that window, pull `(report_source, description)` activity from
   `Logs/Report/` (fast, simple, unconditional, no owner) and
   `(report_source, description, owner)` activity from `Logs/Hist/`
   (`Create`/`Rename Scheduled Report` and `Remove Finished Report`
   events specifically — owner-attributed, and the only source that
   captures ad hoc (`"a"`) usage at all).
4. Clear the candidate flag on any template whose key matches something
   found in step 3, in either source.
5. Keep the `created`-recency floor from the original redesign spec: a
   template created within the `--years` window hasn't had time to
   accumulate history yet, flag or not — don't let "too new to have run"
   look the same as "old and abandoned."
6. Whatever's still flagged after the full window is scanned is the real
   candidate list — owner-exclusion (`--exclude-owner`/
   `--exclude-owner-regex`) applies on top, unchanged from the original
   spec.

This supersedes the `Logs/Report/`-only version of the rule described in
`2026-08-31-remove-stale-templates-log-based-redesign.md` — that spec
still needs a follow-up revision to reflect the above before
implementation starts (not done in this pass; flagged, not fixed here).

## What we could accomplish today vs. over time

**Today, no changes needed:**
- Deploy the finalized method above for the large majority of manual
  templates — `(report_source, description, owner)` via `Logs/Hist/`
  already resolves nearly all of what used to be the ambiguous 15%,
  using history that already exists (12+ years retained). Nothing to
  wait for.
- Start archiving `Rptprint/printlist` going forward, before its ~2-week
  rolling window prunes rows we haven't captured — cheap, additive,
  doesn't touch any live template, and every day not archived is history
  that can't be recovered later.

**Requires building something new:**
- The actual parsing/indexing implementation: `Logs/Report/` text
  parsing (straightforward), the `Logs/Hist/` raw-marker pre-filter +
  `logprint | translate` pipeline (needs the validation noted above
  first), and a caching layer so the 3-year window doesn't get
  fully re-parsed on every invocation.
- The tagging feature remains optional polish for the residual
  same-owner-same-description edge case, not a prerequisite — see above.
  If built: either a new mode on `remove_stale_templates.py` or a small
  standalone script (open question), touching `schedlist` and the
  underlying `.set` file consistently per row.

**Requires waiting, only if tagging is ever built:**
- A newly-tagged template needs its own accumulated history under the
  new description before it can be judged independently — a short
  observation window (weeks to a month) catches renewed activity, but
  isn't enough to conclude staleness on its own; that wants something
  closer to the full `--years` window.
