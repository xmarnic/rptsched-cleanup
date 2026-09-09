#!/usr/bin/env python3
import argparse
import sys
from datetime import datetime
from pathlib import Path

from rptsched_lib.operators import (
    find_operator_mismatches,
    apply_mismatches,
    read_operator,
    rewrite_operator,
    read_operator_manifest,
    OperatorRewriteError,
)
from rptsched_lib.quarantine import InvalidManifestError, make_run_dir


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

    if args.restore:
        try:
            rows = read_operator_manifest(args.restore)
        except InvalidManifestError as err:
            print(str(err), file=sys.stderr)
            return 1

        restored = 0
        skipped = 0
        for row in rows:
            template_id = row["id"]
            old_operator = row["old_operator"]
            new_operator = row["new_operator"]
            current = read_operator(args.data_dir, template_id)

            if current == old_operator:
                skipped += 1
                continue
            if current == new_operator:
                try:
                    rewrite_operator(args.data_dir, template_id, old_operator)
                except OSError as err:
                    print(
                        "Failed to restore operator for {}: {}".format(template_id, err),
                        file=sys.stderr,
                    )
                    return 1
                restored += 1
                continue

            print(
                "Cannot restore {}: current operator {!r} matches neither old ({!r}) nor new ({!r})".format(
                    template_id, current, old_operator, new_operator
                ),
                file=sys.stderr,
            )
            return 1

        print("Restored {} operator value(s), skipped {} already-restored".format(restored, skipped))
        return 0

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
