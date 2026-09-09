#!/usr/bin/env python3
"""
Coherent single-command wrapper around detect_stale_templates.py,
report_stale_templates.py, and execute_stale_templates.py -- calls each
one's real main(argv) exactly as you'd invoke it by hand, so this can
never drift from what those tools do standalone. Manages its own
default location for the candidates file and activity-index cache
under --work-dir, so day-to-day use doesn't require juggling those
paths yourself.

  (bare)            detect only -- saves candidates into --work-dir, prints a count
  --report          also prints the full human-readable report
  --execute         quarantines using --work-dir's saved candidates file
  --restore RUN_DIR restores a prior run

--execute requires a candidates file already sitting in --work-dir --
it does not silently re-detect first, since that would skip the review
step. Run without --execute (optionally with --report) first, look at
what it found, then --execute once you're satisfied. (execute_stale_
templates.py itself still re-verifies against live data before it
touches anything, same as always -- this is a separate, deliberate gate
on top of that: you have to have actually looked at a report before
this wrapper will let you act on it.)

Usage:
    quarantine_stale_templates.py --data-dir D --logs-report-dir R --logs-hist-dir H
    quarantine_stale_templates.py --data-dir D --logs-report-dir R --logs-hist-dir H --report
    quarantine_stale_templates.py --data-dir D --quarantine-dir Q --logs-report-dir R --logs-hist-dir H --execute
    quarantine_stale_templates.py --data-dir D --quarantine-dir Q --restore RUN_DIR
"""
import argparse
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import detect_stale_templates
import execute_stale_templates
import report_stale_templates
from rptsched_lib.cli import run

DEFAULT_WORK_DIR = Path("stale_templates_work")
CANDIDATES_FILENAME = "candidates.jsonl"
CACHE_FILENAME = "activity_index_cache.json"


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--quarantine-dir", type=Path, help="Required with --execute/--restore.")
    parser.add_argument("--logs-report-dir", type=Path, help="Required unless --restore is given.")
    parser.add_argument("--logs-hist-dir", type=Path, help="Required unless --restore is given.")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--exclude-owner", action="append", default=[], metavar="OWNER")
    parser.add_argument("--exclude-owner-regex", action="append", default=[], metavar="PATTERN")
    parser.add_argument(
        "--work-dir", type=Path, default=DEFAULT_WORK_DIR,
        help="Holds candidates.jsonl and the activity-index cache. Persistent by default ({}), "
             "so --execute has something to act on and repeated detect/report runs stay "
             "cheap.".format(DEFAULT_WORK_DIR),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--report", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--restore", metavar="RUN_DIR", type=Path)
    return parser


def _exclude_argv(args):
    argv = []
    for owner in args.exclude_owner:
        argv += ["--exclude-owner", owner]
    for pattern in args.exclude_owner_regex:
        argv += ["--exclude-owner-regex", pattern]
    return argv


def _run_detect(args, cache_path, candidates_path):
    detect_argv = [
        "--data-dir", str(args.data_dir),
        "--logs-report-dir", str(args.logs_report_dir),
        "--logs-hist-dir", str(args.logs_hist_dir),
        "--index-cache-path", str(cache_path),
        "--years", str(args.years),
    ] + _exclude_argv(args)

    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = detect_stale_templates.main(detect_argv)
    if exit_code != 0:
        return exit_code

    candidates_path.write_text(buf.getvalue())
    return 0


def _run_report(args, candidates_path):
    report_argv = [
        "--data-dir", str(args.data_dir),
        "--candidates-file", str(candidates_path),
    ] + _exclude_argv(args)
    return report_stale_templates.main(report_argv)


def _run_execute(args, cache_path, candidates_path):
    execute_argv = [
        "--data-dir", str(args.data_dir),
        "--quarantine-dir", str(args.quarantine_dir),
        "--candidates-file", str(candidates_path),
        "--logs-report-dir", str(args.logs_report_dir),
        "--logs-hist-dir", str(args.logs_hist_dir),
        "--index-cache-path", str(cache_path),
        "--years", str(args.years),
    ] + _exclude_argv(args)
    return execute_stale_templates.main(execute_argv)


def _run_restore(args):
    return execute_stale_templates.main([
        "--data-dir", str(args.data_dir),
        "--quarantine-dir", str(args.quarantine_dir),
        "--restore", str(args.restore),
    ])


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.restore:
        if args.quarantine_dir is None:
            parser.error("--quarantine-dir is required with --restore")
        return _run_restore(args)

    if args.logs_report_dir is None or args.logs_hist_dir is None:
        parser.error("--logs-report-dir and --logs-hist-dir are required unless --restore is given")

    args.work_dir.mkdir(parents=True, exist_ok=True)
    cache_path = args.work_dir / CACHE_FILENAME
    candidates_path = args.work_dir / CANDIDATES_FILENAME

    if args.execute:
        if args.quarantine_dir is None:
            parser.error("--quarantine-dir is required with --execute")
        if not candidates_path.is_file():
            parser.error(
                "No candidates file found at {} -- run without --execute first to detect "
                "and review candidates.".format(candidates_path)
            )
        return _run_execute(args, cache_path, candidates_path)

    exit_code = _run_detect(args, cache_path, candidates_path)
    if exit_code != 0:
        return exit_code

    if args.report:
        return _run_report(args, candidates_path)

    count = len(candidates_path.read_text().strip().splitlines())
    print("{} candidate(s) detected, saved to {}. Re-run with --report to review, "
          "--execute to quarantine.".format(count, candidates_path))
    return 0


if __name__ == "__main__":
    run(main)
