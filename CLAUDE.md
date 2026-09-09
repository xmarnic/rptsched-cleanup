# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Scripts to clean up `rptsched/`, a Symphony ILS (SirsiDynix) report-scheduler
data directory, in production at `/software/WYLD/Unicorn/Rptsched/`. Three
cleanup categories are implemented (orphans, stale saved templates, operator
sync); a fourth (scheduled report removal candidates) is parked, ideation
only. New work still generally follows the `superpowers:brainstorming` →
`superpowers:writing-plans` workflow for anything that changes behavior, not
just adds a test.

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

Four categories. Three are implemented; the fourth is parked.

1. **Orphans** — `<id>.*` file groups with no `schedlist` line. Spec:
   `docs/superpowers/specs/2026-07-24-remove-orphans-design.md`.
2. **Stale saved templates** — manual (`frequency_flag == "n"`) templates
   with no activity found in `Logs/Report/` or `Logs/Hist/` within
   `--years`. Original spec (quarantine/restore mechanics, still current):
   `docs/superpowers/specs/2026-07-24-remove-stale-templates-design.md`.
   That spec's candidate-selection logic is superseded — `schedlist`'s own
   `last_run`/`created` fields turned out not to carry a usage signal for
   manual templates (confirmed empirically after a production incident);
   see `docs/superpowers/specs/2026-08-31-remove-stale-templates-log-based-redesign.md`
   for what replaced it.
3. **Operator sync** — corrects a `.set` file's `operator|` field to match
   `schedlist`'s owner for that id when they've drifted apart. Spec:
   `docs/superpowers/specs/2026-07-24-sync-operator-field-design.md`.
   Doesn't quarantine or delete anything — the only category that mutates
   a file's contents in place rather than moving it.
4. **Scheduled report removal candidates** — recurring-schedule templates
   that are inactive per the inactivity rule. **Parked** — see note below.

### Tool shape: composable plumbing + a porcelain wrapper per category

Each of the three implemented categories is split into small,
single-purpose tools connected by a JSONL candidate stream (one JSON
object per line, one stream per category), plus one coherent wrapper most
usage should go through day to day. Full rationale and design decisions:
`docs/superpowers/specs/2026-09-09-composable-cli-pipeline-design.md`.

**Plumbing** (`detect_<category>.py` / `report_<category>.py` /
`execute_<category>.py`, e.g. `detect_stale_templates.py`):
- `detect_<category>.py` — pure detection. Copies `--rptsched-dir` first
  (`schedlist` is a single flat-file index for the entire report
  scheduler — too sensitive to read live from a tool that only needs
  read access), then emits one JSON record per candidate to stdout.
  Writes nothing else, except stale-templates' `--index-cache-path` (an
  explicit, deliberate exception — see below).
- `report_<category>.py` — reads a JSONL stream (stdin or
  `--candidates-file`) plus `--rptsched-dir`, prints a human-readable
  analysis. Never recomputes detection.
- `execute_<category>.py` — reads a **reviewed** JSONL file via
  `--candidates-file` (never stdin, since an unreviewed pipe input here
  would defeat the review gate). Before mutating anything, re-runs
  detection fresh against **live** `--rptsched-dir` (no copy — it's about to
  mutate that directory anyway) and diffs it against the reviewed file
  **per candidate ID, not whole-stream**: a reviewed ID missing from the
  fresh result, or present with changed identity-defining fields (e.g.
  stale-templates' `raw_line`), aborts loudly with nothing written; a
  fresh-only candidate (new since review) is simply ignored — this tool
  only ever acts on what was reviewed. This is deliberately per-ID: an
  unrelated `schedlist`/file change between review and execute is the
  common case on a live production server, not an edge case, and
  whole-stream equality would abort on it constantly. Also bundles
  `--restore RUN_DIR`.
- Stale-templates only: `build_activity_index_cache.py` keeps one shared
  `--index-cache-path` warm (incremental, mtime-keyed) — point
  `detect_stale_templates.py` and `execute_stale_templates.py` at the
  same path so re-verification at execute time is normally a cheap
  incremental update, not a cold re-decode of `Logs/Hist/`.

**Porcelain** (`quarantine_stale_templates.py`, `quarantine_orphans.py`,
`sync_operators.py` — the interface most usage should go through):
one command per category, calling the plumbing tools' real `main(argv)`
in-process (zero logic duplication, can't drift from what the standalone
tools do). Named for what `--execute` actually does — "quarantine" for
the two categories that move files, "sync" for the one that corrects a
field in place; none of them are named "remove," since nothing is ever
deleted.

```
(bare)              detect only — saves candidates into --work-dir, prints a count
--report             also prints the full human-readable report
--execute             quarantines/applies using --work-dir's saved candidates file
--restore RUN_DIR     restores a prior run
```

`--work-dir` defaults to a persistent per-category directory
(`stale_templates_work/`, `orphans_work/`, `operators_work/`), holding the
candidates file and (for stale-templates) the activity-index cache — pass
it explicitly to control the location. `--execute` deliberately **requires**
a candidates file already sitting in `--work-dir`; it will not silently
re-detect first, since skipping straight from a bare invocation to
`--execute` would skip the review step entirely. (The underlying
`execute_<category>.py` tool still independently re-verifies against live
data regardless — the wrapper's requirement is a separate, additional
gate: you have to have actually looked at a report before the wrapper
lets you act on it.)

### Safety guarantees, restated for the split

- **Dry-run writes nothing** — true of `detect`/`report`, with one
  explicit, deliberate exception: `detect_stale_templates.py` writes to
  `--index-cache-path`. That's disposable derived cache state, not
  `rptsched/` production data or an audit artifact, so it doesn't violate
  the spirit of the guarantee — but it does mean "writes nothing" now
  means "writes nothing to `--rptsched-dir` or `--quarantine-dir`," not
  literally zero bytes written anywhere.
- **Quarantine is always a move, never a delete.** Unchanged.
- **`--restore` is idempotent and resumable**: moves each manifest row's
  file back from `dest_path` to `source_path`, skipping any row whose
  `dest_path` no longer exists (already restored), aborting immediately on
  an individual failure. The run subfolder is the status signal — files
  still present means restore is incomplete, and re-running `--restore`
  on the same subfolder is always safe. `manifest.csv` is never deleted.
- **Schedlist restore preserves creation order, idempotent by id.**
  `execute_stale_templates.py` saves the exact removed lines verbatim
  (`removed_schedlist_lines.txt`, sourced from the *fresh re-detection*,
  never the reviewed file — the reviewed file is authorization for which
  IDs, never the source of what gets written) so `--restore` can, after
  the file-restore phase completes, re-insert them into the *current*
  `schedlist` (not overwrite it — it may have legitimate edits since the
  removal run) at the position matching each line's `created` timestamp,
  without disturbing any line that wasn't touched — `schedlist`'s real
  on-disk order is append/chronological by `created`, not alphabetical by
  id. Idempotent by id, since a restore might be retried.

### Shared plumbing modules (`rptsched_lib/`)

- `quarantine.py` — `make_run_dir`, `move_groups_to_quarantine`,
  `restore_run`, plus generalized `write_manifest`/`read_manifest`
  (parameterized by fieldnames, header-validated on read — raises
  `InvalidManifestError` on mismatch). Used by every category that
  quarantines files.
- `atomic.py` — one shared `atomic_write(path, content)`
  (mkstemp + conditional copystat + os.replace), replacing what used to
  be three independently duplicated copies.
- `cli.py` — `run(main, argv)`, the standard entry point for every CLI
  tool in this repo; handles `BrokenPipeError` cleanly so piping output
  into `head`/`less`/another tool doesn't crash with a traceback.
- Candidate-detection logic stays separate per category — scripts must
  not invoke each other's detection logic (e.g. stale-templates must not
  hand off to orphans' "sweep all current orphans," since that would
  catch unrelated pre-existing orphans in the wrong run).

## Local data for testing

- `rptsched/` — a local mirror of production `Rptsched/` used for realistic
  testing. Gitignored — never commit it. Currently a full snapshot of
  production (`rptsched.tar.gz`, ~1 month old as of 2026-08-27, extracted
  in place): 5,311-line `schedlist` plus ~12,000 companion `.set`/
  `.selans`/etc. files, not a curated subset. `tests/test_stale_templates_pipeline_integration.py`
  skips itself via `unittest.skipUnless` when this directory is absent,
  and re-extracting a fresh snapshot may shift dataset-dependent expected
  values baked into it. Orphans and operator-sync don't yet have an
  equivalent real-data integration suite — only unit-level CLI tests
  against synthetic fixtures — worth adding if this dataset changes
  enough to matter.

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
