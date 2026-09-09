# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Scripts to clean up `rptsched/`, a Symphony ILS (SirsiDynix) report-scheduler
data directory, in production at `/software/WYLD/Unicorn/Rptsched/`. This repo
currently contains no implementation code yet — work is in the design/spec
phase using the `superpowers:brainstorming` → `superpowers:writing-plans`
workflow.

## Tooling

**Python 3.6.8, standard library only.** The production server is RHEL8
without admin access, so no dependable way to `pip install` third-party
packages — everything must run on stdlib alone (`argparse`, `csv`,
`pathlib`, `shutil.move`, `re`, `datetime`, `tempfile` + `os.replace` for
atomic file replacement, `unittest` for tests). 3.6.8 also means: no
dataclasses (3.7+), no f-string `=` debugging or walrus operator (3.8+) —
use plain classes/namedtuples and regular f-strings.

pip is present on the box (`pip 21.3.1`, user-local install under
`/software/WYLD/.local/lib/python3.6/site-packages/pip`) but not tied to
admin rights, so it doesn't change the stdlib-only constraint above.
Someday it'd be worth writing an install script for this repo's scripts —
not started.

**Read `rptsched-domain-reference.md` first, in full, before working on any
cleanup logic.** It is the authoritative source for: `schedlist` file format,
what counts as an orphan / stale saved template / scheduled-report removal
candidate, the inactivity rule, the ACQ exclusion, and which mtimes are
trustworthy vs. not. Do not re-derive or guess at this domain logic — it's
already fully specified there.

## Cleanup scope

Three independent removal categories, each gets its own spec and script:

1. **Orphans** — `<id>.*` file groups with no `schedlist` line. Spec done:
   `docs/superpowers/specs/2026-07-24-remove-orphans-design.md`.
2. **Stale saved templates** — manual (`frequency_flag == "n"`) templates
   with no activity found in `Logs/Report/` or `Logs/Hist/` within
   `--years`. Original spec (modes/quarantine/restore mechanics, still
   current): `docs/superpowers/specs/2026-07-24-remove-stale-templates-design.md`.
   Candidate-selection logic in that spec is superseded — `schedlist`'s
   own `last_run`/`created` fields turned out not to carry a usage
   signal for manual templates (confirmed empirically after a production
   incident); see `docs/superpowers/specs/2026-08-31-remove-stale-templates-log-based-redesign.md`
   for what replaced it.
3. **Scheduled report removal candidates** — recurring-schedule templates
   that are inactive per the inactivity rule. **Parked** — see note below.

Each script follows the same interface: `--data-dir` and
`--quarantine-dir` always passed explicitly (never hardcoded, so a script
can run against the local `rptsched/` copy before ever touching
production), dry-run by default (console-only, nothing written), an
`--execute` mode that moves matching files into a timestamped subfolder
under quarantine (`orphans_<timestamp>`, `templates_<timestamp>`, etc.)
plus a `manifest.csv`, and a `--restore <run-subfolder>` mode that
reverses a run. Quarantine is always a move, never a delete.

`--restore` is **idempotent and resumable**: it moves each manifest row's
file back from `dest_path` to `source_path`, skipping any row whose
`dest_path` no longer exists (already restored by an earlier attempt),
and aborts immediately on an individual failure rather than continuing.
The run subfolder itself is the status signal — files still present means
restore is incomplete, and re-running `--restore` on the same subfolder
is always safe. `manifest.csv` is never deleted, so once a run is fully
restored (subfolder empty of data files) it still doubles as the
completeness proof and a permanent audit record.

The stale-templates script (and, presumably, the scheduled-reports script
once spec'd) additionally rewrites `schedlist` itself — removing candidate
lines via write-temp-file + atomic-rename, never an in-place edit — since
those categories, unlike orphans, have a live `schedlist` line that would
otherwise dangle. It saves the exact removed lines verbatim
(`removed_schedlist_lines.txt`, also never deleted) so `--restore` can,
*after* the file-restore phase completes, re-insert them into the
*current* `schedlist` (not blindly overwrite it, since it may have
legitimate edits made after the removal run) and insert each one at the
position matching its `created` timestamp, without disturbing the
relative order of any line that wasn't touched — `schedlist`'s real
on-disk order is append/chronological (by `created`), not alphabetical by
id. (A prior version of this logic wrongly re-sorted the whole file by id
on every restore — confirmed and fixed via a local execute→restore
round-trip test against `rptsched/`, see
`docs/testing/2026-08-31-run-behavior-test-procedure.md` for how it was
found.) That re-insert step is itself idempotent — it skips any line
whose id is already present in the current schedlist — since a schedlist
id must stay unique even if a restore is retried.

The move/manifest/restore mechanics (given a data-dir, quarantine-dir, a
run-name prefix, and a set of target ids: create the run subfolder, move
each id's file group, write `manifest.csv`, restore from it idempotently)
are meant to live in one shared internal module used by all the cleanup
scripts. Candidate-detection logic and whether/how `schedlist` gets
touched stay separate per script — scripts must not invoke each other's
detection logic (e.g. stale-templates must not hand off to orphans'
"sweep all current orphans" after rewriting schedlist, since that would
catch unrelated pre-existing orphans in the wrong run).

## Local data for testing

- `rptsched/` — a local mirror of production `Rptsched/` used for realistic
  testing. Gitignored — never commit it. Currently a full snapshot of
  production (`rptsched.tar.gz`, ~1 month old as of 2026-08-27, extracted
  in place): 5,311-line `schedlist` plus ~12,000 companion `.set`/
  `.selans`/etc. files, not a curated subset. The three integration test
  suites (`tests/test_remove_*_integration.py`) skip themselves via
  `unittest.skipUnless` when this directory is absent, and re-extracting a
  fresh snapshot may shift dataset-dependent expected values baked into
  those tests (e.g. the known orphan count in
  `test_remove_orphans_integration.py`) — check those after refreshing the
  snapshot.

## Specs

Design specs live under `docs/superpowers/specs/`, one file per cleanup
category, following the `superpowers:brainstorming` skill's naming
convention (`YYYY-MM-DD-<topic>-design.md`). Check there before assuming a
category's behavior — the specs are more detailed than the summary above.

## Parked: scheduled report removal candidates

Deliberately not spec'd yet. A recurring schedule (`d1`/`w1`-`w7`/`m1`-`m31`)
is, in a sense, a signal of validity — someone set it up on purpose — so
"inactive per the inactivity rule" alone feels like a weaker removal
signal here than it is for manual templates. Ideas to revisit when this
category comes up again, not acted on yet:

- Since new BI software has taken over for most list/stats use cases,
  scheduled reports whose `report_source` is a plain list or statistics
  report may be reasonable candidates even if not otherwise flagged by
  the inactivity rule — usage may have shifted to the BI tool without the
  old schedule ever being turned off.
- Symphony schedules can be suspended; a suspended schedule that hasn't
  run in ~1 year could be treated as a removal candidate on its own,
  separate from (or in addition to) the general inactivity rule.

Both are ideation only — no selection criteria, thresholds, or script
behavior has been decided.
