# rptsched Domain Reference

Plain-language reference for what `rptsched/` is, how its files are
interpreted, and where everything lives. No implementation details or
specs here — just the domain facts needed to reason about cleanup work.

## What rptsched/ is

`rptsched/` is the Symphony ILS (SirsiDynix's integrated library system)
report-scheduler data directory. Every report a staff member has ever
saved from Symphony's report-scheduling screen leaves a record here. The
directory holds two things:

1. A single flat-file index, `schedlist`, with one line per **saved
   report template**.
2. Two files per template, named by a 4-character ID: `<id>.set` (the
   machine-readable report configuration) and `<id>.selans` (the
   human-readable version of the same answers). Some templates also have
   extra companion files sharing that ID with other extensions (`.user`,
   `.am`, `.srch`, `.id`, `.ids`, `.mn`, `.chk`, `.bak`, `.ap`, etc.) —
   these travel with the template as one group.

A 4-character ID is the join key across all of this: `schedlist` line ↔
`<id>.set` ↔ `<id>.selans` ↔ any other `<id>.*` companion file.

## schedlist line format

Pipe-delimited, roughly 19-20 fields per line. The fields that matter for
interpretation:

| Field index | Name | Notes |
|---|---|---|
| 0 | id | 4-character ID, matches `<id>.set`/`<id>.selans` on disk |
| 1 | report_type | Symphony report type code |
| 2 | description | Human-entered title/description |
| 3 | frequency_flag | See below |
| 4 | created | `YYYYMMDDHHMM` |
| 5 | last_run | `YYYYMMDDHHMM`, or `0000000000` sentinel meaning "never run" |
| 6 | owner | Staff username/ID that owns the template |


**frequency_flag** distinguishes two kinds of saved template:

- `n` — saved but only ever run manually. Not on a recurring schedule.
- `d1`, `w1`-`w7`, `m1`-`m31` — genuinely on a recurring schedule (daily,
  a specific weekday, or a specific day of the month).

## Definitions

**Saved template** — any row in `schedlist`. Every saved template has a
matching `<id>.set`/`<id>.selans` pair (and possibly more companion
files) on disk. This is the umbrella term; the two categories below are
subsets of it, split by `frequency_flag`.

**Scheduled report** — a saved template whose `frequency_flag` is
recurring (`d1`/`w1`-`w7`/`m1`-`m31`). Symphony will keep running this on
its own schedule for as long as the template exists.

**Orphan** — an `<id>.set` file on disk with **no corresponding line in
`schedlist`**. This can only happen to the `.set`/companion files, never
to a `schedlist` line by itself (a `schedlist` line with no files would
just be a template pointing at nothing — not something this system
produces). Orphans are leftovers from report runs that were generated but
never saved as a template. They are not templates, not scheduled, and
carry no owner/frequency/date information of their own — just whatever
can be inferred by reading inside the `.set` file.

**Inactivity rule** — the shared definition of "unused," applied to
saved templates (never applied to orphans, which have no `last_run`/
`created` fields to evaluate):

```
last_run != 0000000000  AND  last_run is 3+ years before today
        OR
last_run == 0000000000  AND  created  is 3+ years before today
```

i.e. prefer `last_run` as the signal; fall back to `created` only if the
template has genuinely never been run.

**Stale saved template (removal candidate)** — a saved template where
`frequency_flag == "n"` (manual) **and** it satisfies the inactivity rule.
Nobody is running it by hand anymore, and nothing will run it
automatically either.

**Scheduled report removal candidate** — a saved template where
`frequency_flag` is recurring **and** it satisfies the inactivity rule.
Note this looks at `last_run`/`created`, not "is the schedule still
turned on" — a recurring template can be inactive if, e.g., its schedule
stopped firing or its output silently stopped mattering to anyone.

**Owner exclusion** — regardless of inactivity, a saved template whose
`owner` field is excluded via `--exclude-owner` (exact match) or
`--exclude-owner-regex` (regex match) is left alone entirely and is
never a removal candidate (stale or scheduled). This is a CLI-configured
mechanism, not hardcoded — the scripts ship with no owner exclusions by
default. For WYLD, Acquisitions-owned templates (`owner` containing
`ACQ`, case-insensitive) are out of scope for this cleanup effort by
policy, not by usage pattern; that's expressed as
`--exclude-owner-regex ACQ` in this site's own invocation, not as
built-in script behavior.

## Trustworthy vs. untrustworthy signals

- `.set` file mtimes are **unreliable** — some unrelated periodic process
  on the server bulk-touches `.set` files, so their mtime does not mean
  "last used."
- `.selans` mtime and `schedlist`'s `last_run` field **agree with each
  other** and are the trustworthy signal for when a template was actually
  last used.

## Where this lives, in production

- **Real data directory (the actual `Rptsched` dir being cleaned):**
  `/software/WYLD/Unicorn/Rptsched/`
- **Where cleanup scripts run from:**
  `/software/WYLD/Nic/Scripts/rptsched-cleanup/`
- **Where quarantined (moved, not deleted) files land:** a `quarantine/`
  directory alongside the scripts themselves (i.e. under
  `/software/WYLD/Nic/Scripts/rptsched-cleanup/quarantine/`) — visible,
  not dot-hidden, and never inside `Rptsched/` itself. Both the data
  directory and quarantine directory are always passed in explicitly
  (never hardcoded), so tooling can be run safely against a local copy
  before ever touching the production path.

## Local development copies (this repo)

Both are gitignored — never committed, never present except as a working
copy on a dev machine:

- **`rptsched/`** — a full local mirror of production `Rptsched/`
  (5,311 `schedlist` lines, ~12,000 files) for realistic testing.
- **`rptsched_sample/`** — a smaller, stratified-representative subset
  (227 IDs, 473 files: 187 sampled saved templates + 40 sampled orphans)
  built by `scripts/make_sample_rptsched.py` from `rptsched/`. The sample
  deliberately keeps proportional coverage of every combination that
  matters for cleanup logic: ACQ vs. non-ACQ owner, manual vs. recurring
  frequency flag, and active vs. inactive by the rule above — so it
  exercises the same edge cases as the full directory at a fraction of
  the size.
