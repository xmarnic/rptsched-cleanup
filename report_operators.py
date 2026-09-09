#!/usr/bin/env python3
"""
Human-readable summary of an operator-mismatch candidate stream
produced by detect_operators.py. Pure stream formatter -- no --data-dir
needed at all, since every field it prints is already in the stream.

Usage:
    python3 detect_operators.py --data-dir /path/to/rptsched > candidates.jsonl
    python3 report_operators.py < candidates.jsonl
"""
import argparse
import json
import sys
from pathlib import Path


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

    print("{} operator mismatch(es) found".format(len(candidates)))
    for c in sorted(candidates, key=lambda c: c["id"]):
        print("  {}: {} -> {}".format(c["id"], c["old_operator"], c["new_operator"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
