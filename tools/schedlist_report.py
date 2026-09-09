#!/usr/bin/env python3
"""
Stats on remove_stale_templates.py's stale-template candidates, read
directly from schedlist rather than parsed out of saved console output.

Reuses the exact same library functions remove_stale_templates.py's dry
run calls (rptsched_lib.templates.find_stale_template_candidates,
rptsched_lib.activity_index.build_activity_index), so the candidate set
here can't drift from what a real dry run would report. This tool never
touches --execute/--restore and never writes into --data-dir or any
production quarantine dir, so it isn't bound by remove_stale_templates.py's
"dry run writes nothing" guarantee -- it caches the built activity index
by default, across runs, to avoid re-running logprint | translate over
years of unchanged Logs/Hist/ months on every invocation.

--data-dir is never opened directly: it's copied into --work-dir first
(schedlist is a single flat-file index for the entire report scheduler --
not a file to risk touching directly for a read-only reporting tool).

Usage:
    python3 schedlist_report.py --data-dir /path/to/rptsched \
        --logs-report-dir /path/to/Logs/Report \
        --logs-hist-dir /path/to/Logs/Hist
"""
import argparse
import difflib
import shutil
import sys
from collections import Counter, namedtuple
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rptsched_lib.activity_index import build_activity_index, is_active
from rptsched_lib.hist_log import find_hist_files
from rptsched_lib.report_log import find_log_files
from rptsched_lib.templates import count_manual_templates, find_stale_template_candidates, years_before

DEFAULT_WORK_DIR = Path("schedlist_report_work")
CACHE_FILENAME = "activity_index_cache.json"
DATA_COPY_DIRNAME = "data_dir_copy"


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--logs-report-dir", required=True, type=Path)
    parser.add_argument("--logs-hist-dir", required=True, type=Path)
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument(
        "--exclude-owner", action="append", default=[], metavar="OWNER",
        help="Exclude templates whose owner exactly matches OWNER (case-insensitive). Repeatable.",
    )
    parser.add_argument(
        "--exclude-owner-regex", action="append", default=[], metavar="PATTERN",
        help="Exclude templates whose owner matches regex PATTERN (case-insensitive). Repeatable.",
    )
    parser.add_argument(
        "--work-dir", type=Path, default=DEFAULT_WORK_DIR,
        help="Holds the --data-dir copy and the activity-index cache. Persistent by default ({}) "
             "so repeated runs reuse the cache instead of re-decoding Logs/Hist/ from scratch. "
             "Safe to delete between runs -- it holds nothing but derived/copied data.".format(DEFAULT_WORK_DIR),
    )
    return parser


ActiveTemplate = namedtuple("ActiveTemplate", ["id", "report_source", "description", "owner"])


def _collect_active_manual_templates(data_dir, activity_index, exclude_owners, exclude_owner_regexes):
    """
    Manual templates (frequency_flag == "n") that ARE active per the same
    activity index remove_stale_templates.py uses -- i.e. never touched by
    removal at all. Separate from find_stale_template_candidates on
    purpose: that function only tells you about the stale side, and this
    tool's active-duplicates check needs the opposite population. Applies
    the same owner exclusions as the stale-candidate path for consistency
    (e.g. skips ACQ if that's passed in), but doesn't reuse
    find_stale_template_candidates's private owner-matching helper --
    detection logic for a genuinely different check stays separate, same
    as this repo's other cleanup categories.
    """
    import re
    compiled_regexes = [re.compile(pattern, re.IGNORECASE) for pattern in exclude_owner_regexes]
    templates = []
    with (data_dir / "schedlist").open() as f:
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
            owner_lower = owner.lower()
            if any(owner_lower == pattern.lower() for pattern in exclude_owners):
                continue
            if any(regex.search(owner) for regex in compiled_regexes):
                continue
            if not is_active(activity_index, report_source, description, owner):
                continue
            templates.append(ActiveTemplate(
                id=template_id, report_source=report_source, description=description, owner=owner,
            ))
    return templates


def _line_diff_count(lines_a, lines_b):
    # Count of changed/inserted/deleted lines via SequenceMatcher opcodes --
    # a rough similarity signal, not a semantic comparison. Two real
    # duplicates can still show a nonzero count here (e.g. one resaved on a
    # newer Symphony version picks up extra auto-enumerated fields and a
    # newer copyright banner), so this is a "worth a look" prioritization
    # hint, not a confirmed-duplicate verdict -- .set's internal field
    # semantics aren't documented in this repo, so no attempt is made to
    # tell meaningful selection-criteria differences apart from
    # version/schema noise.
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

    today = datetime.now()
    threshold = years_before(today, args.years)

    # Same wrong/unmounted/mistyped-log-path footgun remove_stale_templates.py
    # guards against: an empty match here would silently make every manual
    # template look inactive, which would poison every stat below.
    if not find_log_files(args.logs_report_dir, since=threshold):
        print(
            "No files found under --logs-report-dir ({}) within the last {} years. "
            "Refusing to proceed -- check the path.".format(args.logs_report_dir, args.years),
            file=sys.stderr,
        )
        return 1
    if not find_hist_files(args.logs_hist_dir, since=threshold):
        print(
            "No files found under --logs-hist-dir ({}) within the last {} years. "
            "Refusing to proceed -- check the path.".format(args.logs_hist_dir, args.years),
            file=sys.stderr,
        )
        return 1

    args.work_dir.mkdir(parents=True, exist_ok=True)
    data_copy = args.work_dir / DATA_COPY_DIRNAME
    if data_copy.exists():
        shutil.rmtree(data_copy)
    shutil.copytree(args.data_dir, data_copy)

    cache_path = args.work_dir / CACHE_FILENAME
    activity_index = build_activity_index(
        args.logs_report_dir, args.logs_hist_dir, since=threshold, cache_path=cache_path,
    )

    candidates = find_stale_template_candidates(
        data_copy, activity_index, years=args.years, today=today,
        exclude_owners=args.exclude_owner, exclude_owner_regexes=args.exclude_owner_regex,
    )
    total_manual = count_manual_templates(data_copy)
    total_removed = len(candidates)

    if total_removed == 0:
        print("No stale templates found; nothing to report.")
        return 0

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    pct = 100.0 * total_removed / total_manual
    print("{} of {} manual templates removed ({:.1f}%)".format(total_removed, total_manual, pct))
    total_files = sum(len(c.filenames) for c in candidates.values())
    print("{} companion file(s) across all removed templates ({:.1f} avg per template)".format(
        total_files, total_files / total_removed))

    print()
    print("=" * 60)
    print("BY OWNER -- share of total removal")
    print("=" * 60)
    owner_counts = Counter(c.owner for c in candidates.values())
    rows = []
    for owner, count in owner_counts.most_common():
        rows.append((owner, count, "{:.1f}%".format(100.0 * count / total_removed)))
    _print_table(rows, ["owner", "removed_count", "pct_of_total_removed"])

    print()
    print("=" * 60)
    print("BY REPORT_SOURCE -- share of total removal")
    print("=" * 60)
    source_counts = Counter(c.report_source for c in candidates.values())
    rows = []
    for report_source, count in source_counts.most_common():
        rows.append((report_source, count, "{:.1f}%".format(100.0 * count / total_removed)))
    _print_table(rows, ["report_source", "removed_count", "pct_of_total_removed"])

    print()
    print("=" * 60)
    print("BY CREATED YEAR -- age of removed templates")
    print("=" * 60)
    year_counts = Counter(c.created[:4] for c in candidates.values())
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
    active_templates = _collect_active_manual_templates(
        data_copy, activity_index, exclude_owners=args.exclude_owner, exclude_owner_regexes=args.exclude_owner_regex,
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
    for c in candidates.values():
        by_owner.setdefault(c.owner, []).append(c)
    for owner in sorted(by_owner):
        group = sorted(by_owner[owner], key=lambda c: (c.report_source, c.description))
        print("\n{} ({} removed)".format(owner, len(group)))
        rows = [(c.id, c.report_source, c.description, c.created) for c in group]
        _print_table(rows, ["id", "report_source", "description", "created"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
