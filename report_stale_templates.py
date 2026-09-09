#!/usr/bin/env python3
"""
Human-readable analysis of a stale-templates candidate stream produced
by detect_stale_templates.py. Reads JSONL (stdin by default, or
--candidates-file) plus --rptsched-dir -- never recomputes the activity
index or the candidate list itself, so this tool has no --logs-report-dir/
--logs-hist-dir/--index-cache-path of its own.

--rptsched-dir is copied first, same reasoning as detect_stale_templates.py:
schedlist is a single flat-file index for the entire report scheduler,
too sensitive to read directly from a tool that only ever needs read
access.

The "active functional duplicates" section is the one part of this tool
that isn't purely stream-derived: it independently determines the
active (non-candidate) manual template population by taking every
manual, non-excluded schedlist row NOT present in the candidate stream
-- not by rebuilding the activity index -- so this stays cheap (a
schedlist scan, no Logs/Hist/ decode) at the cost of a known, accepted
imprecision: a template inside the recency floor (too new to judge, per
detect_stale_templates.py's created-window carve-out) is neither a
candidate nor confirmed-active, but this complement-based population
counts it as active anyway. Harmless here since this section is
awareness-only and never feeds into any removal decision -- see
docs/superpowers/specs/2026-09-09-composable-cli-pipeline-design.md.

--exclude-owner/--exclude-owner-regex must match whatever was passed to
detect_stale_templates.py, so the active-population complement lines up
with what was actually excluded during detection.

Usage:
    python3 detect_stale_templates.py --rptsched-dir ... --logs-report-dir ... \
        --logs-hist-dir ... --index-cache-path ... > candidates.jsonl
    python3 report_stale_templates.py --rptsched-dir /path/to/rptsched < candidates.jsonl
"""
import argparse
import json
import re
import shutil
import sys
from collections import Counter, namedtuple
from pathlib import Path
from tempfile import TemporaryDirectory

from rptsched_lib.cli import run
from rptsched_lib.templates import count_manual_templates

ActiveTemplate = namedtuple("ActiveTemplate", ["id", "report_source", "description", "owner"])


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rptsched-dir", required=True, type=Path)
    parser.add_argument(
        "--candidates-file", type=Path, default=None,
        help="JSONL candidate stream. Defaults to stdin.",
    )
    parser.add_argument(
        "--exclude-owner", action="append", default=[], metavar="OWNER",
        help="Must match what was passed to detect_stale_templates.py. Repeatable.",
    )
    parser.add_argument(
        "--exclude-owner-regex", action="append", default=[], metavar="PATTERN",
        help="Must match what was passed to detect_stale_templates.py. Repeatable.",
    )
    return parser


def _read_candidates(candidates_file):
    lines = candidates_file.open() if candidates_file else sys.stdin
    try:
        return [json.loads(line) for line in lines if line.strip()]
    finally:
        if candidates_file:
            lines.close()


def _collect_active_manual_templates(rptsched_dir, candidate_ids, exclude_owners, exclude_owner_regexes):
    compiled_regexes = [re.compile(pattern, re.IGNORECASE) for pattern in exclude_owner_regexes]
    templates = []
    with (rptsched_dir / "schedlist").open() as f:
        for line in f:
            raw_line = line.rstrip("\n")
            if not raw_line.strip():
                continue
            fields = raw_line.split("|")
            if len(fields) < 7:
                continue
            template_id, report_source, description, frequency_flag, created, last_run, owner = fields[0:7]
            if frequency_flag != "n":
                continue
            if template_id in candidate_ids:
                continue
            owner_lower = owner.lower()
            if any(owner_lower == pattern.lower() for pattern in exclude_owners):
                continue
            if any(regex.search(owner) for regex in compiled_regexes):
                continue
            templates.append(ActiveTemplate(
                id=template_id, report_source=report_source, description=description, owner=owner,
            ))
    return templates


def _line_diff_count(lines_a, lines_b):
    import difflib
    matcher = difflib.SequenceMatcher(None, lines_a, lines_b)
    return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in matcher.get_opcodes() if tag != "equal")


def _print_table(rows, headers):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for row in rows:
        print(fmt.format(*row))


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    candidates = _read_candidates(args.candidates_file)
    total_removed = len(candidates)

    if total_removed == 0:
        print("No stale templates in the candidate stream; nothing to report.")
        return 0

    with TemporaryDirectory(prefix="report_stale_templates_") as tmp:
        data_copy = Path(tmp) / "rptsched_dir_copy"
        shutil.copytree(args.rptsched_dir, data_copy)

        total_manual = count_manual_templates(data_copy)

        print("=" * 60)
        print("SUMMARY")
        print("=" * 60)
        pct = 100.0 * total_removed / total_manual
        print("{} of {} manual templates removed ({:.1f}%)".format(total_removed, total_manual, pct))
        total_files = sum(len(c["filenames"]) for c in candidates)
        print("{} companion file(s) across all removed templates ({:.1f} avg per template)".format(
            total_files, total_files / total_removed))

        print()
        print("=" * 60)
        print("BY OWNER -- share of total removal")
        print("=" * 60)
        owner_counts = Counter(c["owner"] for c in candidates)
        rows = []
        for owner, count in owner_counts.most_common():
            rows.append((owner, count, "{:.1f}%".format(100.0 * count / total_removed)))
        _print_table(rows, ["owner", "removed_count", "pct_of_total_removed"])

        print()
        print("=" * 60)
        print("BY REPORT_SOURCE -- share of total removal")
        print("=" * 60)
        source_counts = Counter(c["report_source"] for c in candidates)
        rows = []
        for report_source, count in source_counts.most_common():
            rows.append((report_source, count, "{:.1f}%".format(100.0 * count / total_removed)))
        _print_table(rows, ["report_source", "removed_count", "pct_of_total_removed"])

        print()
        print("=" * 60)
        print("BY CREATED YEAR -- age of removed templates")
        print("=" * 60)
        year_counts = Counter(c["created"][:4] for c in candidates)
        rows = sorted(year_counts.items())
        _print_table(rows, ["created_year", "removed_count"])

        print()
        print("=" * 60)
        print("ACTIVE FUNCTIONAL DUPLICATES -- informational only, not tied to removal")
        print("=" * 60)
        print(
            "Stale candidates above are removed regardless of duplication -- both\n"
            "copies are independently unused, so there's nothing to pick between.\n"
            "This section looks at the opposite population instead: ACTIVE templates\n"
            "(never touched by removal), compared by owner regardless of description\n"
            "text, to catch cases the activity index's (report_source, description)\n"
            "join key can't see -- e.g. the same report saved twice under different\n"
            "descriptions. Only byte-identical .set matches are shown; without a\n"
            "description match to anchor on, anything less than exact is just noise.\n"
            "This is awareness only, for a possible manual consolidation effort --\n"
            "an active template someone depends on isn't safe to remove just because\n"
            "it has a twin, so nothing here feeds into any removal decision."
        )
        candidate_ids = {c["id"] for c in candidates}
        active_templates = _collect_active_manual_templates(
            data_copy, candidate_ids, exclude_owners=args.exclude_owner, exclude_owner_regexes=args.exclude_owner_regex,
        )
        by_owner_active = {}
        for t in active_templates:
            by_owner_active.setdefault(t.owner, []).append(t)

        found_any = False
        for owner in sorted(by_owner_active):
            group = sorted(by_owner_active[owner], key=lambda t: t.id)
            rows = []
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    path_a = data_copy / (a.id + ".set")
                    path_b = data_copy / (b.id + ".set")
                    if not path_a.is_file() or not path_b.is_file():
                        continue
                    lines_a = path_a.read_text(errors="replace").splitlines()
                    lines_b = path_b.read_text(errors="replace").splitlines()
                    if _line_diff_count(lines_a, lines_b) == 0:
                        rows.append((a.id, a.description, b.id, b.description))
            if rows:
                found_any = True
                print("\n{} ({} active templates checked)".format(owner, len(group)))
                _print_table(rows, ["id_a", "description_a", "id_b", "description_b"])

        if not found_any:
            print("\nNo byte-identical .set matches found among active templates within any owner.")

        print()
        print("=" * 60)
        print("FULL LISTING -- grouped by owner, sorted by report_source within each")
        print("=" * 60)
        by_owner = {}
        for c in candidates:
            by_owner.setdefault(c["owner"], []).append(c)
        for owner in sorted(by_owner):
            group = sorted(by_owner[owner], key=lambda c: (c["report_source"], c["description"]))
            print("\n{} ({} removed)".format(owner, len(group)))
            rows = [(c["id"], c["report_source"], c["description"], c["created"]) for c in group]
            _print_table(rows, ["id", "report_source", "description", "created"])

    return 0


if __name__ == "__main__":
    run(main)
