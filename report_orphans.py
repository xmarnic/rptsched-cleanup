#!/usr/bin/env python3
"""
Human-readable summary of an orphan candidate stream produced by
detect_orphans.py. Pure stream formatter -- no --data-dir needed at
all, since every field it prints (id, filenames) is already in the
stream.

Usage:
    python3 detect_orphans.py --data-dir /path/to/rptsched > candidates.jsonl
    python3 report_orphans.py < candidates.jsonl
"""
import argparse
import json
import sys
from pathlib import Path
from rptsched_lib.cli import run


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--candidates-file", type=Path, default=None,
        help="JSONL candidate stream. Defaults to stdin.",
    )
    return parser


def _read_candidates(candidates_file):
    lines = candidates_file.open() if candidates_file else sys.stdin
    try:
        return [json.loads(line) for line in lines if line.strip()]
    finally:
        if candidates_file:
            lines.close()


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    candidates = _read_candidates(args.candidates_file)
    total_files = sum(len(c["filenames"]) for c in candidates)

    print("{} orphan id(s), {} file(s) would be moved".format(len(candidates), total_files))
    for c in sorted(candidates, key=lambda c: c["id"]):
        print("  {}: {}".format(c["id"], ", ".join(c["filenames"])))
    return 0


if __name__ == "__main__":
    run(main)
