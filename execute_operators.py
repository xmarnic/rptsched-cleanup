#!/usr/bin/env python3
"""
Mutates: applies a reviewed set of operator-field corrections. Reads a
REVIEWED JSONL file (the literal artifact a human signed off on) via
--candidates-file -- never stdin, matching execute_stale_templates.py/
execute_orphans.py's reasoning.

Before touching anything, validates every reviewed ID against LIVE
--data-dir, in two steps:

  1. The current schedlist owner for that ID must still equal the
     reviewed new_operator -- otherwise the schedlist owner changed
     since review and the reviewed new_operator is stale. This is the
     operator-sync equivalent of execute_stale_templates.py's raw_line
     check: it catches drift in the field the review was actually
     based on, not just the .set file being touched.
  2. The current .set operator value is classified against the
     reviewed (old_operator, new_operator) pair via
     rptsched_lib.operators.classify_current_value: "matches_old" means
     the write still needs to happen; "matches_new" means it's already
     applied (e.g. an earlier interrupted run of this same reviewed
     file) and is recorded in the manifest without rewriting anything;
     "conflict" means something else changed it and the whole batch
     aborts, nothing written.

Any single conflict aborts the entire batch before anything is
written, same sequencing rule as the other two categories. A
reviewed-only-partially-applied state from an interrupted prior run is
handled by the "matches_new" case, not treated as an error.

--restore reuses the exact same classify_current_value, with the two
directions swapped: "matches_new" means still-applied, needs reverting;
"matches_old" means already restored, skip; "conflict" aborts. This is
the same logic sync_operator_field.py's restore already had --
formalized here as the shared function execute uses too.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from rptsched_lib.cli import run
from rptsched_lib.operators import (
    OperatorRewriteError,
    apply_reviewed_changes,
    classify_current_value,
    read_operator,
    read_operator_manifest,
    read_schedlist_owners,
    rewrite_operator,
)
from rptsched_lib.quarantine import InvalidManifestError, make_run_dir


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", required=True, type=Path)
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


def _validate_and_classify(data_dir, reviewed):
    """
    Returns (classifications, None) on success, or (None, reason) if any
    reviewed ID should abort the whole batch.
    """
    owners = read_schedlist_owners(data_dir)
    classifications = {}
    for template_id, record in reviewed.items():
        current_owner = owners.get(template_id)
        if current_owner != record["new_operator"]:
            return None, (
                "{}: schedlist owner changed since review (now {!r}, reviewed expected {!r})".format(
                    template_id, current_owner, record["new_operator"])
            )
        current_operator = read_operator(data_dir, template_id)
        classification = classify_current_value(current_operator, record["old_operator"], record["new_operator"])
        if classification == "conflict":
            return None, (
                "{}: current operator {!r} matches neither reviewed old ({!r}) nor new ({!r})".format(
                    template_id, current_operator, record["old_operator"], record["new_operator"])
            )
        classifications[template_id] = classification
    return classifications, None


def _do_restore(args):
    try:
        rows = read_operator_manifest(args.restore)
    except InvalidManifestError as err:
        print(str(err), file=sys.stderr)
        return 1

    restored = 0
    skipped = 0
    for row in rows:
        template_id = row["id"]
        current = read_operator(args.data_dir, template_id)
        classification = classify_current_value(current, row["old_operator"], row["new_operator"])

        if classification == "matches_old":
            skipped += 1
            continue
        if classification == "matches_new":
            try:
                rewrite_operator(args.data_dir, template_id, row["old_operator"])
            except OSError as err:
                print("Failed to restore operator for {}: {}".format(template_id, err), file=sys.stderr)
                return 1
            restored += 1
            continue

        print(
            "Cannot restore {}: current operator {!r} matches neither old ({!r}) nor new ({!r})".format(
                template_id, current, row["old_operator"], row["new_operator"]
            ),
            file=sys.stderr,
        )
        return 1

    print("Restored {} operator value(s), skipped {} already-restored".format(restored, skipped))
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

    classifications, abort_reason = _validate_and_classify(args.data_dir, reviewed)
    if abort_reason is not None:
        print(
            "Refusing to proceed -- the reviewed candidate file no longer matches live data: "
            "{}. Nothing was written. Re-run detect_operators.py, review again, and try "
            "again.".format(abort_reason),
            file=sys.stderr,
        )
        return 1

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = make_run_dir(args.quarantine_dir, "operators", timestamp)
    try:
        rows = apply_reviewed_changes(args.data_dir, run_dir, reviewed, classifications)
    except OperatorRewriteError as err:
        print(str(err), file=sys.stderr)
        return 1

    print("Corrected {} operator value(s) in {}".format(len(rows), run_dir))
    return 0


if __name__ == "__main__":
    run(main)
