#!/usr/bin/env python3
"""
Keeps one persistent --index-cache-path fresh -- no candidate detection,
no --data-dir, nothing else. detect_stale_templates.py and
execute_stale_templates.py's internal re-detect both read/update the
same cache path this tool maintains; running this on its own (e.g. via
cron, or by hand before an interactive detect | report session) means
those two pay an incremental update instead of a cold rebuild.

Usage:
    python3 build_activity_index_cache.py \
        --logs-report-dir /path/to/Logs/Report \
        --logs-hist-dir /path/to/Logs/Hist \
        --index-cache-path /path/to/activity_index_cache.json
"""
import argparse
import sys
from pathlib import Path

from rptsched_lib.stale_candidates import EmptyLogDirectoryError, build_index


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--logs-report-dir", required=True, type=Path)
    parser.add_argument("--logs-hist-dir", required=True, type=Path)
    parser.add_argument("--index-cache-path", required=True, type=Path)
    parser.add_argument("--years", type=int, default=3)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        build_index(
            args.logs_report_dir, args.logs_hist_dir,
            years=args.years, index_cache_path=args.index_cache_path,
        )
    except EmptyLogDirectoryError as err:
        print(str(err), file=sys.stderr)
        return 1

    print("Activity index cache refreshed at {}".format(args.index_cache_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
