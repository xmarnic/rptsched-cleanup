#!/usr/bin/env python3
"""
Mutates: moves a reviewed set of orphan file groups into quarantine.
Reads a REVIEWED JSONL file (the literal artifact a human signed off
on) via --candidates-file -- never stdin, since accepting an unreviewed
pipe input here would defeat the point of the review gate.

Before touching anything, re-runs rptsched_lib.orphans.find_orphan_groups
fresh against live --rptsched-dir (no copy -- this is about to mutate that
same directory anyway) and diffs it against the reviewed file, per
reviewed ID: a reviewed ID missing from the fresh result, or present
with a different (sorted) filename set, means something changed since
review -- abort loudly, nothing written. A fresh-only orphan (new since
review) is simply ignored -- this tool only ever acts on what was
reviewed. Same per-ID diff shape as execute_stale_templates.py, for the
same reason: an unrelated schedlist/file change between review and
execute is the common case in a live production directory, not an edge
case.

On a clean diff, mutation moves the FRESH re-detect's filenames for
every reviewed ID -- never the reviewed file's -- matching
execute_stale_templates.py's "reviewed file is authorization, never
content" rule.

--restore reverses a prior run via quarantine.restore_run, unchanged --
orphans never touch schedlist, so there's no sidecar file to manage.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rptsched_lib.cli import run
from rptsched_lib.orphans import find_orphan_groups
from rptsched_lib.quarantine import (
    QuarantineMoveError,
    QuarantineRestoreError,
    make_run_dir,
    move_groups_to_quarantine,
    restore_run,
)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rptsched-dir", required=True, type=Path)
    parser.add_argument("--quarantine-dir", required=True, type=Path)
    parser.add_argument(
        "--candidates-file", type=Path, default=None,
        help="The reviewed JSONL file to act on. Required unless --restore is given.",
    )
    parser.add_argument("--restore", metavar="RUN_DIR", type=Path, default=None)
    return parser


def _read_reviewed_candidates(candidates_file: Path):
    reviewed = {}
    with candidates_file.open() as f:
        for line in f:
            if not line.strip():
                continue
            record = json.loads(line)
            reviewed[record["id"]] = record
    return reviewed


def _diff_against_fresh(reviewed, fresh_groups):
    for file_id, record in reviewed.items():
        fresh_filenames = fresh_groups.get(file_id)
        if fresh_filenames is None:
            return "{}: no longer an orphan (schedlist or files changed since review)".format(file_id)
        if sorted(fresh_filenames) != sorted(record["filenames"]):
            return "{}: file group changed since review".format(file_id)
    return None


def _do_restore(args):
    try:
        result = restore_run(args.restore)
    except QuarantineRestoreError as err:
        print(str(err), file=sys.stderr)
        return 1
    print("Restored {} file(s), skipped {} already-restored".format(result["restored"], result["skipped"]))
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.restore:
        return _do_restore(args)

    if args.candidates_file is None:
        parser.error("--candidates-file is required unless --restore is given")

    reviewed = _read_reviewed_candidates(args.candidates_file)
    if not reviewed:
        print("No candidates in the reviewed file; nothing to do.")
        return 0

    fresh_groups = find_orphan_groups(args.rptsched_dir)

    abort_reason = _diff_against_fresh(reviewed, fresh_groups)
    if abort_reason is not None:
        print(
            "Refusing to proceed -- the reviewed candidate file no longer matches a fresh "
            "re-detection: {}. Nothing was written. Re-run composables/detect_orphans.py, review again, "
            "and try again.".format(abort_reason),
            file=sys.stderr,
        )
        return 1

    groups = {file_id: fresh_groups[file_id] for file_id in reviewed}
    total_files = sum(len(filenames) for filenames in groups.values())

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = make_run_dir(args.quarantine_dir, "orphans", timestamp)
    try:
        move_groups_to_quarantine(args.rptsched_dir, run_dir, groups, moved_at=timestamp)
    except QuarantineMoveError as err:
        print(str(err), file=sys.stderr)
        return 1

    print("Moved {} file(s) across {} orphan id(s) into {}".format(total_files, len(groups), run_dir))
    return 0


if __name__ == "__main__":
    run(main)
