#!/usr/bin/env python3
"""
Pure detection for the orphans category. Emits one JSON object per
orphan id to stdout (JSONL) -- no pretty-printing, no mutation.

Copies --data-dir before reading it, same reasoning as
detect_stale_templates.py: schedlist is a single flat-file index for
the entire report scheduler, too sensitive to read directly from a
tool that only ever needs read access. execute_orphans.py calls
rptsched_lib.orphans.find_orphan_groups directly against live
--data-dir for its pre-mutation re-verification instead of shelling out
to this CLI, to avoid paying a second full-directory copy on every
mutating run.

Usage:
    python3 detect_orphans.py --data-dir /path/to/rptsched > candidates.jsonl
"""
import argparse
import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from rptsched_lib.cli import run
from rptsched_lib.orphans import find_orphan_groups

SCHEMA_VERSION = 1


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", required=True, type=Path)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    with TemporaryDirectory(prefix="detect_orphans_") as tmp:
        data_copy = Path(tmp) / "data_dir_copy"
        shutil.copytree(args.data_dir, data_copy)
        groups = find_orphan_groups(data_copy)

    for file_id in sorted(groups):
        record = {"schema_version": SCHEMA_VERSION, "id": file_id, "filenames": sorted(groups[file_id])}
        print(json.dumps(record))
    return 0


if __name__ == "__main__":
    run(main)
