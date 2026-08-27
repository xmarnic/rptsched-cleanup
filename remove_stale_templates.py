#!/usr/bin/env python3
import argparse
import sys
from datetime import datetime
from pathlib import Path

from rptsched_lib.templates import count_manual_templates, find_stale_template_candidates
from rptsched_lib.schedlist import remove_lines, insert_lines
from rptsched_lib.quarantine import (
    QuarantineMoveError,
    QuarantineRestoreError,
    make_run_dir,
    move_groups_to_quarantine,
    read_manifest,
    restore_run,
)

REMOVED_LINES_FILENAME = "removed_schedlist_lines.txt"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove stale saved templates (manual, inactive) from a Symphony Rptsched directory."
    )
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--quarantine-dir", required=True, type=Path)
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument(
        "--exclude-owner", action="append", default=[], metavar="OWNER",
        help="Exclude templates whose owner exactly matches OWNER (case-insensitive). Repeatable.",
    )
    parser.add_argument(
        "--exclude-owner-regex", action="append", default=[], metavar="PATTERN",
        help="Exclude templates whose owner matches regex PATTERN (case-insensitive, unanchored search). Repeatable.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--restore", metavar="RUN_DIR", type=Path)
    return parser


def _write_removed_lines(run_dir: Path, removed_lines) -> Path:
    path = Path(run_dir) / REMOVED_LINES_FILENAME
    with path.open("w") as f:
        for line in removed_lines:
            f.write(line + "\n")
    return path


def _read_removed_lines(run_dir: Path):
    path = Path(run_dir) / REMOVED_LINES_FILENAME
    if not path.exists():
        return []
    with path.open() as f:
        return [line.rstrip("\n") for line in f if line.strip()]


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.restore:
        try:
            file_result = restore_run(args.restore)
        except QuarantineRestoreError as err:
            print(str(err), file=sys.stderr)
            return 1

        removed_lines = _read_removed_lines(args.restore)
        schedlist_result = insert_lines(args.data_dir, removed_lines)

        print("Restored {} file(s), skipped {} already-restored".format(
            file_result["restored"], file_result["skipped"]))
        print("Re-inserted {} schedlist line(s), skipped {} already present".format(
            schedlist_result["inserted"], schedlist_result["skipped"]))
        return 0

    candidates = find_stale_template_candidates(
        args.data_dir, years=args.years,
        exclude_owners=args.exclude_owner,
        exclude_owner_regexes=args.exclude_owner_regex,
    )
    total_files = sum(len(c.filenames) for c in candidates.values())

    if not args.execute:
        total_manual = count_manual_templates(args.data_dir)
        print("DRY RUN: {} stale template(s) out of {} manual template(s) total, {} file(s) would be moved".format(
            len(candidates), total_manual, total_files))
        for template_id in sorted(candidates):
            c = candidates[template_id]
            print("  {}: {} | owner={} | freq={} | created={} | last_run={} | files={}".format(
                c.id, c.description, c.owner, c.frequency_flag, c.created, c.last_run,
                ", ".join(c.filenames)))
        return 0

    if not candidates:
        print("No stale templates found; nothing to do.")
        return 0

    groups = {template_id: c.filenames for template_id, c in candidates.items()}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = make_run_dir(args.quarantine_dir, "templates", timestamp)
    try:
        move_groups_to_quarantine(args.data_dir, run_dir, groups, moved_at=timestamp)
    except QuarantineMoveError as err:
        all_filenames = [
            filename
            for file_id in sorted(groups)
            for filename in sorted(groups[file_id])
        ]
        moved_filenames = set()
        manifest_path = run_dir / "manifest.csv"
        if manifest_path.exists():
            moved_filenames = {row["filename"] for row in read_manifest(run_dir)}
        remaining = [f for f in all_filenames if f not in moved_filenames]
        failed_filename = remaining[0] if remaining else "<unknown file>"
        print("{} (file: {})".format(err, failed_filename), file=sys.stderr)
        return 1

    removed_lines = [candidates[template_id].raw_line for template_id in sorted(candidates)]
    _write_removed_lines(run_dir, removed_lines)
    remove_lines(args.data_dir, set(candidates.keys()))

    print("Moved {} file(s) across {} stale template(s) into {}".format(
        total_files, len(candidates), run_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
