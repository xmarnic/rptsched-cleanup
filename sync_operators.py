#!/usr/bin/env python3
"""
Coherent single-command wrapper around detect_operators.py,
report_operators.py, and execute_operators.py -- calls each one's real
main(argv) exactly as you'd invoke it by hand, so this can never drift
from what those tools do standalone. Manages its own default location
for the candidates file under --work-dir.

  (bare)            detect only -- saves candidates into --work-dir, prints a count
  --report          also prints the full human-readable report
  --execute         applies operator-field corrections using --work-dir's saved candidates
  --restore RUN_DIR restores a prior run

--execute requires a candidates file already sitting in --work-dir --
it does not silently re-detect first, since that would skip the review
step. Run without --execute first, look at what it found, then
--execute once you're satisfied. Unlike the other two categories, this
one never quarantines anything -- it corrects a .set file's operator
field in place to match schedlist's owner.

--data-dir can be derived from a single --unicorn-root (or
RPTSCHED_UNICORN_ROOT env var) instead of passed directly --
Rptsched/'s location relative to the Unicorn install root is Symphony's
own convention, not a per-site choice. Pass --data-dir directly to
override (e.g. for local testing). --quarantine-dir has no such default
-- where this run's audit manifest lives is an operator choice, always
required explicitly with --execute/--restore.

Usage:
    export RPTSCHED_UNICORN_ROOT=/software/WYLD/Unicorn
    sync_operators.py --report
    sync_operators.py --quarantine-dir Q --execute
    sync_operators.py --quarantine-dir Q --restore RUN_DIR

    # or fully explicit, e.g. for local testing:
    sync_operators.py --data-dir D --report
"""
import argparse
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import detect_operators
import execute_operators
import report_operators
from rptsched_lib.cli import run, unicorn_paths, unicorn_root_default

DEFAULT_WORK_DIR = Path("operators_work")
CANDIDATES_FILENAME = "candidates.jsonl"


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--unicorn-root", type=Path, default=unicorn_root_default(),
        help="Symphony Unicorn install root (or set RPTSCHED_UNICORN_ROOT). Derives --data-dir "
             "when it isn't passed directly.",
    )
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--quarantine-dir", type=Path, help="Required with --execute/--restore.")
    parser.add_argument(
        "--work-dir", type=Path, default=DEFAULT_WORK_DIR,
        help="Holds candidates.jsonl. Persistent by default ({}), so --execute has something "
             "to act on.".format(DEFAULT_WORK_DIR),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--report", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--restore", metavar="RUN_DIR", type=Path)
    return parser


def _run_detect(args, candidates_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = detect_operators.main(["--data-dir", str(args.data_dir)])
    if exit_code != 0:
        return exit_code
    candidates_path.write_text(buf.getvalue())
    return 0


def _run_report(candidates_path):
    return report_operators.main(["--candidates-file", str(candidates_path)])


def _run_execute(args, candidates_path):
    return execute_operators.main([
        "--data-dir", str(args.data_dir),
        "--quarantine-dir", str(args.quarantine_dir),
        "--candidates-file", str(candidates_path),
    ])


def _run_restore(args):
    return execute_operators.main([
        "--data-dir", str(args.data_dir),
        "--quarantine-dir", str(args.quarantine_dir),
        "--restore", str(args.restore),
    ])


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.data_dir is None and args.unicorn_root is not None:
        args.data_dir, _, _ = unicorn_paths(args.unicorn_root)
    if args.data_dir is None:
        parser.error("--data-dir is required (or set --unicorn-root / RPTSCHED_UNICORN_ROOT)")

    if args.restore:
        if args.quarantine_dir is None:
            parser.error("--quarantine-dir is required with --restore")
        return _run_restore(args)

    args.work_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = args.work_dir / CANDIDATES_FILENAME

    if args.execute:
        if args.quarantine_dir is None:
            parser.error("--quarantine-dir is required with --execute")
        if not candidates_path.is_file():
            parser.error(
                "No candidates file found at {} -- run without --execute first to detect "
                "and review candidates.".format(candidates_path)
            )
        return _run_execute(args, candidates_path)

    exit_code = _run_detect(args, candidates_path)
    if exit_code != 0:
        return exit_code

    if args.report:
        return _run_report(candidates_path)

    count = len(candidates_path.read_text().strip().splitlines())
    print("{} candidate(s) detected, saved to {}. Re-run with --report to review, "
          "--execute to apply.".format(count, candidates_path))
    return 0


if __name__ == "__main__":
    run(main)
