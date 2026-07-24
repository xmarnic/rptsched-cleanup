#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

from rptsched_cleanup.orphans import find_orphan_groups


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

    groups = find_orphan_groups(args.data_dir)
    total_files = sum(len(filenames) for filenames in groups.values())

    print("DRY RUN: {} orphan id(s), {} file(s) would be moved".format(len(groups), total_files))
    for file_id in sorted(groups):
        print("  {}: {}".format(file_id, ", ".join(sorted(groups[file_id]))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
