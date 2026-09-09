#!/usr/bin/env python3
"""
Compile stats on a remove_stale_templates.py dry-run's console output.

Usage:
    python3 analyze_dry_run.py <dry_run_output.txt>

Parses the "DRY RUN: N stale template(s) out of M manual template(s)
total, ..." summary line and the per-candidate lines that follow it
(format: "  id: description | report_source=X | owner=Y | freq=n |
created=YYYYMMDDHHMM | files=..."), then reports:

  - overall percent of manual templates being removed
  - percent of the total removal each owner accounts for
  - report_source breakdown (the definitive/normalized field --
    description is free text and can collide across genuinely different
    templates)
  - created-year distribution, as a rough age check -- created is the
    one timestamp still trusted for manual templates; last_run is
    deliberately not part of this (see remove_stale_templates.py's dry
    run output, which omits it on purpose)
  - file-count totals, as a rough removal footprint

Accepts output from either before or after the report_type ->
report_source rename (matches whichever label the file actually uses).
"""
import argparse
import re
import sys
from collections import Counter

SUMMARY_RE = re.compile(
    r"DRY RUN:\s*(\d+)\s*stale template\(s\)\s*out of\s*(\d+)\s*manual template\(s\)\s*total"
)
CANDIDATE_RE = re.compile(
    r"^\s*(?P<id>\S+):\s*(?P<description>.*?)\s*\|\s*report_(?:type|source)=(?P<report_source>\S+)"
    r"\s*\|\s*owner=(?P<owner>\S+)\s*\|\s*freq=(?P<freq>\S+)\s*\|\s*created=(?P<created>\S+)"
    r"\s*\|\s*files=(?P<files>.*)$"
)


def parse(path):
    total_manual = None
    candidates = []
    with open(path) as f:
        for line in f:
            summary_match = SUMMARY_RE.search(line)
            if summary_match:
                total_manual = int(summary_match.group(2))
                continue
            candidate_match = CANDIDATE_RE.match(line)
            if candidate_match:
                candidates.append(candidate_match.groupdict())
    return total_manual, candidates


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dry_run_output", help="Path to saved dry-run console output")
    args = parser.parse_args(argv)

    total_manual, candidates = parse(args.dry_run_output)
    total_removed = len(candidates)

    if total_removed == 0:
        print("No candidate lines found -- check the file/format.", file=sys.stderr)
        return 1

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if total_manual:
        pct = 100.0 * total_removed / total_manual
        print("{} of {} manual templates removed ({:.1f}%)".format(
            total_removed, total_manual, pct))
    else:
        print("{} templates removed (total manual template count not found in "
              "file -- overall percent unavailable)".format(total_removed))
    total_files = sum(
        len([f for f in c["files"].split(",") if f.strip()]) for c in candidates
    )
    print("{} companion file(s) across all removed templates ({:.1f} avg per template)".format(
        total_files, total_files / total_removed))

    print()
    print("=" * 60)
    print("BY OWNER -- share of total removal")
    print("=" * 60)
    owner_counts = Counter(c["owner"] for c in candidates)
    rows = []
    for owner, count in owner_counts.most_common():
        pct_of_removed = 100.0 * count / total_removed
        rows.append((owner, count, "{:.1f}%".format(pct_of_removed)))
    _print_table(rows, ["owner", "removed_count", "pct_of_total_removed"])

    print()
    print("=" * 60)
    print("BY REPORT_SOURCE -- share of total removal")
    print("=" * 60)
    source_counts = Counter(c["report_source"] for c in candidates)
    rows = []
    for report_source, count in source_counts.most_common():
        pct_of_removed = 100.0 * count / total_removed
        rows.append((report_source, count, "{:.1f}%".format(pct_of_removed)))
    _print_table(rows, ["report_source", "removed_count", "pct_of_total_removed"])

    print()
    print("=" * 60)
    print("BY CREATED YEAR -- age of removed templates")
    print("=" * 60)
    year_counts = Counter()
    unparseable = 0
    for c in candidates:
        created = c["created"]
        if len(created) >= 4 and created[:4].isdigit():
            year_counts[created[:4]] += 1
        else:
            unparseable += 1
    rows = [(year, count) for year, count in sorted(year_counts.items())]
    _print_table(rows, ["created_year", "removed_count"])
    if unparseable:
        print("({} candidate(s) had an unparseable created value)".format(unparseable))

    print()
    print("=" * 60)
    print("REPORT_SOURCE x DESCRIPTION -- for spotting ambiguous report_source collisions")
    print("=" * 60)
    combo_counts = Counter((c["report_source"], c["description"]) for c in candidates)
    dupes = {k: v for k, v in combo_counts.items() if v > 1}
    if dupes:
        rows = [(rs, desc, count) for (rs, desc), count in sorted(dupes.items(), key=lambda kv: -kv[1])]
        _print_table(rows, ["report_source", "description", "count"])
    else:
        print("No (report_source, description) pair appears more than once.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
