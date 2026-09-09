#!/usr/bin/env python3
"""
Pure detection for the operator-sync category. Emits one JSON object
per operator mismatch to stdout (JSONL) -- no pretty-printing, no
mutation. Ids skipped during detection (missing .set file, or missing
operator line) are printed as WARNINGs to stderr, same as the old
dry-run behavior -- they aren't mismatches, so they don't belong in the
candidate stream.

Copies --rptsched-dir before reading it, same reasoning as
detect_stale_templates.py/detect_orphans.py. execute_operators.py reads
the live .set/schedlist values directly for its pre-mutation check
instead of shelling out to this CLI.

Usage:
    python3 detect_operators.py --rptsched-dir /path/to/rptsched > candidates.jsonl
"""
import argparse
import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from rptsched_lib.cli import run
from rptsched_lib.operators import find_operator_mismatches

SCHEMA_VERSION = 1


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rptsched-dir", required=True, type=Path)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    with TemporaryDirectory(prefix="detect_operators_") as tmp:
        data_copy = Path(tmp) / "rptsched_dir_copy"
        shutil.copytree(args.rptsched_dir, data_copy)
        mismatches, skipped = find_operator_mismatches(data_copy)

    for skip in skipped:
        print("WARNING: {} skipped ({})".format(skip.id, skip.reason), file=sys.stderr)

    for template_id in sorted(mismatches):
        m = mismatches[template_id]
        record = {
            "schema_version": SCHEMA_VERSION,
            "id": m.id,
            "old_operator": m.old_operator,
            "new_operator": m.new_operator,
        }
        print(json.dumps(record))
    return 0


if __name__ == "__main__":
    run(main)
