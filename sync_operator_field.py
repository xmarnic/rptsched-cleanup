#!/usr/bin/env python3
import argparse
import sys
from datetime import datetime
from pathlib import Path

from rptsched_cleanup.operators import find_operator_mismatches, apply_mismatches, OperatorRewriteError
from rptsched_cleanup.quarantine import make_run_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync .set operator field to match schedlist owner in a Symphony Rptsched directory."
    )
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--quarantine-dir", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--restore", metavar="RUN_DIR", type=Path)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    mismatches, skipped = find_operator_mismatches(args.data_dir)
    for skip in skipped:
        print("WARNING: {} skipped ({})".format(skip.id, skip.reason), file=sys.stderr)

    if not args.execute:
        print("DRY RUN: {} operator mismatch(es) found".format(len(mismatches)))
        for template_id in sorted(mismatches):
            m = mismatches[template_id]
            print("  {}: {} -> {}".format(m.id, m.old_operator, m.new_operator))
        return 0

    if not mismatches:
        print("No operator mismatches found; nothing to do.")
        return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = make_run_dir(args.quarantine_dir, "operators", timestamp)

    try:
        rows = apply_mismatches(args.data_dir, run_dir, mismatches)
    except OperatorRewriteError as err:
        print(str(err), file=sys.stderr)
        return 1

    print("Corrected {} operator value(s) in {}".format(len(rows), run_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
