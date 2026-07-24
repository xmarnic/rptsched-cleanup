# run_all — Design Spec

## Purpose

A thin, production-only orchestrator that runs the three existing cleanup
scripts — `remove_orphans`, `remove_stale_templates`, `sync_operator_field`
— in that fixed order against the real production Rptsched directory,
stopping immediately if any one fails. It lives at the repo root alongside
the three scripts it wraps, and is the thing actually invoked from
`/software/WYLD/Nic/Scripts/rptsched-cleanup/` in production.

Unlike the three scripts it wraps, `run_all.py` does **not** take
`--data-dir`/`--quarantine-dir` arguments. Those scripts require them
explicitly (never hardcoded) specifically so they stay safe to run against
local test data. `run_all.py` is different: its entire purpose is being
the fixed production entry point, so it hardcodes the two production
paths from `rptsched-domain-reference.md`:

- `DATA_DIR = /software/WYLD/Unicorn/Rptsched/`
- `QUARANTINE_DIR = /software/WYLD/Nic/Scripts/rptsched-cleanup/quarantine/`

It passes both explicitly to each underlying script's `main()` as CLI-style
args — so the three scripts themselves remain untouched, fully
parameterized, and independently testable on their own. This is the one
deliberate exception to the no-hardcode rule in this repo.

## Invocation mechanics

Imports `remove_orphans`, `remove_stale_templates`, `sync_operator_field`
as Python modules and calls each one's existing `main(argv=None) -> int`
directly, in-process. No subprocesses. This matches how this repo's own
test suites already invoke these scripts, avoids `sys.executable`/path
issues in production, and keeps the whole run in one process for the
combined log (see Logging below).

## CLI

One optional flag: `--execute`.

- Absent (default): all three scripts run in dry-run mode — nothing
  written anywhere, consistent with the safety-first convention the rest
  of this toolkit uses.
- Present: forwarded to all three as `--execute`.

No `--years` passthrough (production runs always use
`remove_stale_templates`'s policy default of 3). No
`--data-dir`/`--quarantine-dir` (hardcoded, see Purpose).

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

The hardcoded production paths don't exist on a dev machine, so tests
never invoke the real underlying scripts' detection logic. Instead:

- Patch `run_all.remove_orphans.main`, `run_all.remove_stale_templates.main`,
  and `run_all.sync_operator_field.main` with fakes that record the exact
  `argv` they were called with and return a controlled exit code —
  verifying call order, argument-passing (`--data-dir`, `--quarantine-dir`,
  and `--execute` forwarding when present), and stop-on-failure behavior
  (a fake that returns nonzero must prevent the next script's fake from
  being called at all).
- Patch the module-level `DATA_DIR`/`QUARANTINE_DIR` constants to point at
  a temp directory, so log-file creation and content can be asserted
  without touching any real path.

This tests `run_all`'s own orchestration logic in isolation; the three
wrapped scripts already have their own full test suites and are not
re-tested here.

## Explicitly out of scope

- Any change to `remove_orphans.py`, `remove_stale_templates.py`, or
  `sync_operator_field.py` themselves — this is a pure orchestration
  layer on top of their existing, unmodified `main()` entry points.
- `--years` or any other per-script option passthrough beyond `--execute`.
- Scheduling (cron, systemd timers, etc.) — `run_all.py` is a script to be
  invoked, not a service; how/when it gets invoked in production is a
  separate concern.
- Retry logic, partial-resume across a failed run, or any restore
  orchestration — each of the three scripts already has its own
  independent `--restore` mode, invoked separately if needed.
