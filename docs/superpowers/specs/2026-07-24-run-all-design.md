# run_all — Design Spec

## Purpose

A thin orchestrator that runs the three existing cleanup scripts —
`remove_orphans`, `remove_stale_templates`, `sync_operator_field` — in
that fixed order, stopping immediately if any one fails. It lives at the
repo root alongside the three scripts it wraps.

Like the three scripts it wraps, `run_all.py` takes `--rptsched-dir` and
`--quarantine-dir` as required CLI arguments — never hardcoded. This
tool is meant to be usable by any consortium running this Symphony
report-scheduler cleanup, not just WYLD, so nothing in the shared code
(including this orchestrator) bakes in one site's production paths or
policy choices. WYLD's own production invocation (concrete paths, plus
`--exclude-owner-regex ACQ` — see below) lives in that site's own
wrapper/cron entry, outside this repo, the same way its owner-exclusion
default does for `remove_stale_templates` on its own.

It passes `--rptsched-dir`/`--quarantine-dir` explicitly to each underlying
script's `main()` as CLI-style args — so the three scripts themselves
remain untouched, fully parameterized, and independently testable on
their own.

`--exclude-owner` and `--exclude-owner-regex` are also accepted, both
repeatable, and forwarded **only** to `remove_stale_templates` — the only
one of the three scripts with an owner-exclusion concept. `remove_orphans`
and `sync_operator_field` don't take these flags, so forwarding them
unconditionally would break those two scripts' argument parsing.

## Invocation mechanics

Imports `remove_orphans`, `remove_stale_templates`, `sync_operator_field`
as Python modules and calls each one's existing `main(argv=None) -> int`
directly, in-process. No subprocesses. This matches how this repo's own
test suites already invoke these scripts, avoids `sys.executable`/path
issues in production, and keeps the whole run in one process for the
combined log (see Logging below).

## CLI

- `--rptsched-dir` (required) — forwarded to all three scripts.
- `--quarantine-dir` (required) — forwarded to all three scripts.
- `--execute` (optional flag) — absent by default (all three scripts run
  in dry-run mode — nothing written anywhere, consistent with the
  safety-first convention the rest of this toolkit uses); when present,
  forwarded to all three as `--execute`.
- `--exclude-owner OWNER` (optional, repeatable) — forwarded only to
  `remove_stale_templates`.
- `--exclude-owner-regex PATTERN` (optional, repeatable) — forwarded only
  to `remove_stale_templates`.

No `--years` passthrough (production runs always use
`remove_stale_templates`'s policy default of 3).

## Sequencing and failure handling

Fixed order: `remove_orphans` → `remove_stale_templates` →
`sync_operator_field`. This mirrors the natural cleanup dependency order
(clear dangling files first, then stale saved templates, then fix
operator/owner drift on whatever templates remain) though the three
scripts' detection logic stays fully independent per their own specs —
`run_all` only sequences them, never hands data between them.

After each script's `main()` call, check its returned exit code:

- **0:** proceed to the next script.
- **nonzero:** print which script failed and its exit code, stop
  immediately — do not run the remaining script(s) — and exit `run_all`
  itself with that same nonzero code.

If all three succeed, print a summary and exit 0.

## Logging

Before running anything, ensure `QUARANTINE_DIR` exists
(`mkdir(parents=True, exist_ok=True)`), then open a new log file at
`QUARANTINE_DIR/run_<YYYYMMDD_HHMMSS>.log` (timestamp captured once, at
`run_all` startup — independent of each underlying script's own internal
timestamp used for its `<prefix>_<timestamp>` run subfolder name).

A `Tee`-style stdout/stderr redirect duplicates everything each script
prints to both the real terminal (so manual runs still see live output)
and the log file (so the run has a permanent record). Each of the three
script invocations is bracketed with a banner line identifying the script
name and its exit code, so a single log file gives a complete, readable
account of one orchestrated run: what ran, in what order, and how each
step concluded.

## Testing

Tests never invoke the real underlying scripts' detection logic:

- Patch `run_all.remove_orphans.main`, `run_all.remove_stale_templates.main`,
  and `run_all.sync_operator_field.main` with fakes that record the exact
  `argv` they were called with and return a controlled exit code —
  verifying call order, argument-passing (`--rptsched-dir`, `--quarantine-dir`,
  and `--execute` forwarding when present), owner-exclusion flags landing
  only in the `remove_stale_templates` call, and stop-on-failure behavior
  (a fake that returns nonzero must prevent the next script's fake from
  being called at all).
- `--rptsched-dir`/`--quarantine-dir` are passed as ordinary CLI args pointing
  at a temp directory, exactly like the three scripts' own test suites
  already do — no module-level constants to patch.

This tests `run_all`'s own orchestration logic in isolation; the three
wrapped scripts already have their own full test suites and are not
re-tested here.

## Explicitly out of scope

- Any change to `remove_orphans.py`, `remove_stale_templates.py`, or
  `sync_operator_field.py` themselves — this is a pure orchestration
  layer on top of their existing, unmodified `main()` entry points.
- `--years` or any other per-script option passthrough beyond `--execute`
  and the `remove_stale_templates`-only owner-exclusion flags.
- Scheduling (cron, systemd timers, etc.) — `run_all.py` is a script to be
  invoked, not a service; how/when it gets invoked in production is a
  separate concern.
- Retry logic, partial-resume across a failed run, or any restore
  orchestration — each of the three scripts already has its own
  independent `--restore` mode, invoked separately if needed.
