#!/usr/bin/env python3
import argparse
import sys
from datetime import datetime
from pathlib import Path

from rptsched_lib.orphans import find_orphan_groups
from rptsched_lib.quarantine import (
    QuarantineMoveError,
    QuarantineRestoreError,
    make_run_dir,
    move_groups_to_quarantine,
    restore_run,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove orphan files (no matching schedlist line) from a Symphony Rptsched directory."
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
            result = restore_run(args.restore)
        except QuarantineRestoreError as err:
            print(str(err), file=sys.stderr)
            return 1
        print("Restored {} file(s), skipped {} already-restored".format(result["restored"], result["skipped"]))
        return 0

    groups = find_orphan_groups(args.data_dir)
    total_files = sum(len(filenames) for filenames in groups.values())

    if not args.execute:
        print("DRY RUN: {} orphan id(s), {} file(s) would be moved".format(len(groups), total_files))
        for file_id in sorted(groups):
            print("  {}: {}".format(file_id, ", ".join(sorted(groups[file_id]))))
        return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = make_run_dir(args.quarantine_dir, "orphans", timestamp)
    try:
        move_groups_to_quarantine(args.data_dir, run_dir, groups, moved_at=timestamp)
    except QuarantineMoveError as err:
        print(str(err), file=sys.stderr)
        return 1
    print("Moved {} file(s) across {} orphan id(s) into {}".format(total_files, len(groups), run_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
