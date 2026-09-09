#!/usr/bin/env python3
"""
Mutates: moves a reviewed set of stale-template candidates into
quarantine and rewrites schedlist. Reads a REVIEWED JSONL file (the
literal artifact a human signed off on) via --candidates-file -- never
stdin, since accepting an unreviewed pipe input here would defeat the
point of the review gate.

Before touching anything, re-runs detect_stale_templates() fresh
against live --data-dir (no copy -- this is about to mutate that same
directory anyway, so copying it first would be a wasted second copy
immediately before the real one) and diffs it against the reviewed
file, per reviewed ID:

  - A reviewed ID missing from the fresh result, or present but with a
    changed raw_line, means something in schedlist changed since
    review -- abort loudly, nothing written.
  - A fresh-only candidate (new since review, not in the reviewed file)
    is simply ignored -- this tool only ever acts on what was reviewed.

This is deliberately per-ID, not whole-stream equality: an unrelated
schedlist row changing between review and execute is the common case in
a live production directory, not an edge case, and whole-stream
equality would abort on it every time. The diff check strictly precedes
run-dir creation, so an abort never leaves an orphaned, manifest-less
run directory behind.

On a clean diff, mutation proceeds using the FRESH re-detect's field
values for every reviewed ID -- never the reviewed file's. The reviewed
file is authorization (which IDs are approved), never the source of
what actually gets moved or written into removed_schedlist_lines.txt.

--restore reverses a prior run exactly as remove_stale_templates.py did
-- unchanged mechanics, quarantine.restore_run plus re-inserting
schedlist lines from removed_schedlist_lines.txt.

--logs-report-dir/--logs-hist-dir/--years/--exclude-owner/
--exclude-owner-regex must match what was passed to
detect_stale_templates.py for the reviewed file to diff cleanly.
--index-cache-path should point at the same shared cache
build_activity_index_cache.py/detect_stale_templates.py use, so this
re-detect is normally a cheap incremental update, not a cold rebuild.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from rptsched_lib.cli import run
from rptsched_lib.quarantine import (
    QuarantineMoveError,
    QuarantineRestoreError,
    make_run_dir,
    move_groups_to_quarantine,
    read_manifest,
    restore_run,
)
from rptsched_lib.schedlist import insert_lines, remove_lines
from rptsched_lib.stale_candidates import EmptyLogDirectoryError, detect_stale_templates

REMOVED_LINES_FILENAME = "removed_schedlist_lines.txt"


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--quarantine-dir", required=True, type=Path)
    parser.add_argument(
        "--candidates-file", type=Path, default=None,
        help="The reviewed JSONL file to act on. Required unless --restore is given.",
    )
    parser.add_argument("--logs-report-dir", type=Path, default=None)
    parser.add_argument("--logs-hist-dir", type=Path, default=None)
    parser.add_argument("--index-cache-path", type=Path, default=None)
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--exclude-owner", action="append", default=[], metavar="OWNER")
    parser.add_argument("--exclude-owner-regex", action="append", default=[], metavar="PATTERN")
    parser.add_argument("--restore", metavar="RUN_DIR", type=Path, default=None)
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


def _read_reviewed_candidates(candidates_file: Path):
    reviewed = {}
    with candidates_file.open() as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            reviewed[record["id"]] = record
    return reviewed


def _diff_against_fresh(reviewed, fresh_candidates):
    """
    Returns None if every reviewed ID is still present in fresh_candidates
    with an unchanged raw_line; otherwise returns a human-readable reason
    the execute must abort. Fresh-only IDs (new since review) are not an
    error -- they're just not acted on.
    """
    for template_id, record in reviewed.items():
        fresh = fresh_candidates.get(template_id)
        if fresh is None:
            return "{}: no longer a stale candidate (schedlist changed since review)".format(template_id)
        if fresh.raw_line != record["raw_line"]:
            return "{}: schedlist line changed since review".format(template_id)
    return None


def _do_restore(args):
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


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.restore:
        return _do_restore(args)

    if args.candidates_file is None:
        parser.error("--candidates-file is required unless --restore is given")
    if args.logs_report_dir is None or args.logs_hist_dir is None:
        parser.error("--logs-report-dir and --logs-hist-dir are required unless --restore is given")

    reviewed = _read_reviewed_candidates(args.candidates_file)
    if not reviewed:
        print("No candidates in the reviewed file; nothing to do.")
        return 0

    today = datetime.now()
    try:
        fresh_candidates = detect_stale_templates(
            args.data_dir, args.logs_report_dir, args.logs_hist_dir,
            years=args.years, today=today,
            exclude_owners=args.exclude_owner, exclude_owner_regexes=args.exclude_owner_regex,
            index_cache_path=args.index_cache_path,
        )
    except EmptyLogDirectoryError as err:
        print(str(err), file=sys.stderr)
        return 1

    abort_reason = _diff_against_fresh(reviewed, fresh_candidates)
    if abort_reason is not None:
        print(
            "Refusing to proceed -- the reviewed candidate file no longer matches a fresh "
            "re-detection: {}. Nothing was written. Re-run detect_stale_templates.py, review "
            "again, and try again.".format(abort_reason),
            file=sys.stderr,
        )
        return 1

    # From here on, only fresh_candidates is used for content -- the
    # reviewed file's job (which IDs are authorized) is already done.
    to_remove = {template_id: fresh_candidates[template_id] for template_id in reviewed}
    total_files = sum(len(c.filenames) for c in to_remove.values())

    groups = {template_id: c.filenames for template_id, c in to_remove.items()}
    timestamp = today.strftime("%Y%m%d_%H%M%S")
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

    removed_lines = [to_remove[template_id].raw_line for template_id in sorted(to_remove)]
    _write_removed_lines(run_dir, removed_lines)
    remove_lines(args.data_dir, set(to_remove.keys()))

    print("Moved {} file(s) across {} stale template(s) into {}".format(
        total_files, len(to_remove), run_dir))
    return 0


if __name__ == "__main__":
    run(main)
