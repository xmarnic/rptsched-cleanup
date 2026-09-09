#!/usr/bin/env python3
"""
Pure detection for the stale-templates category. Emits one JSON object
per candidate to stdout (JSONL) -- no pretty-printing, no mutation.

Copies --data-dir before reading it (schedlist is a single flat-file
index for the entire report scheduler -- too sensitive to read directly
from a tool that only ever needs read access). execute_stale_templates.py
calls rptsched_lib.stale_candidates.detect_stale_templates directly
against live --data-dir for its pre-mutation re-verification instead of
shelling out to this CLI, to avoid paying a second full-directory copy
on every mutating run.

--index-cache-path is required, not optional: skipping it would silently
reintroduce the redundant Logs/Hist/ decode this tool exists to
eliminate. Point it, build_activity_index_cache.py, and
execute_stale_templates.py at the same path.

Usage:
    python3 detect_stale_templates.py --data-dir /path/to/rptsched \
        --logs-report-dir /path/to/Logs/Report \
        --logs-hist-dir /path/to/Logs/Hist \
        --index-cache-path /path/to/activity_index_cache.json \
        > candidates.jsonl
"""
import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from rptsched_lib.candidate_schema import candidate_to_record
from rptsched_lib.stale_candidates import EmptyLogDirectoryError, detect_stale_templates


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--logs-report-dir", required=True, type=Path)
    parser.add_argument("--logs-hist-dir", required=True, type=Path)
    parser.add_argument("--index-cache-path", required=True, type=Path)
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument(
        "--exclude-owner", action="append", default=[], metavar="OWNER",
        help="Exclude templates whose owner exactly matches OWNER (case-insensitive). Repeatable.",
    )
    parser.add_argument(
        "--exclude-owner-regex", action="append", default=[], metavar="PATTERN",
        help="Exclude templates whose owner matches regex PATTERN (case-insensitive, unanchored search). Repeatable.",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    today = datetime.now()

    with tempfile.TemporaryDirectory(prefix="detect_stale_templates_") as tmp:
        data_copy = Path(tmp) / "data_dir_copy"
        shutil.copytree(args.data_dir, data_copy)

        try:
            candidates = detect_stale_templates(
                data_copy, args.logs_report_dir, args.logs_hist_dir,
                years=args.years, today=today,
                exclude_owners=args.exclude_owner, exclude_owner_regexes=args.exclude_owner_regex,
                index_cache_path=args.index_cache_path,
            )
        except EmptyLogDirectoryError as err:
            print(str(err), file=sys.stderr)
            return 1

    for template_id in sorted(candidates):
        print(json.dumps(candidate_to_record(candidates[template_id])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
