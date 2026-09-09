import re
from collections import namedtuple
from datetime import datetime
from pathlib import Path

from rptsched_lib.activity_index import is_active

ID_PATTERN = re.compile(r'^([a-z0-9]{4})\.(.+)$')
DATETIME_FORMAT = "%Y%m%d%H%M"

TemplateCandidate = namedtuple(
    "TemplateCandidate",
    ["id", "raw_line", "report_source", "description", "owner", "frequency_flag", "created", "last_run", "filenames"],
)


def years_before(reference, years):
    try:
        return reference.replace(year=reference.year - years)
    except ValueError:
        # reference is Feb 29 and (year - years) isn't a leap year
        return reference.replace(month=2, day=28, year=reference.year - years)


def _created_within_window(created, threshold):
    # A template that's simply new shouldn't be flagged just because it
    # hasn't shown up in logs yet -- created stays a trustworthy one-time
    # stamp for "n" rows specifically (see rptsched-domain-reference.md).
    return datetime.strptime(created, DATETIME_FORMAT) > threshold


def _group_files_by_id(rptsched_dir: Path):
    groups = {}
    for entry in rptsched_dir.iterdir():
        if not entry.is_file():
            continue
        match = ID_PATTERN.match(entry.name)
        if not match:
            continue
        groups.setdefault(match.group(1), []).append(entry.name)
    return groups


def _is_excluded_owner(owner, exclude_owners, exclude_owner_regexes):
    owner_lower = owner.lower()
    if any(owner_lower == pattern.lower() for pattern in exclude_owners):
        return True
    return any(regex.search(owner) for regex in exclude_owner_regexes)


def count_manual_templates(rptsched_dir):
    rptsched_dir = Path(rptsched_dir)
    count = 0
    with (rptsched_dir / "schedlist").open() as f:
        for line in f:
            raw_line = line.rstrip("\n")
            if not raw_line.strip():
                continue
            fields = raw_line.split("|")
            if fields[3] == "n":
                count += 1
    return count


def find_stale_template_candidates(rptsched_dir, activity_index, years=3, today=None, exclude_owners=(), exclude_owner_regexes=()):
    rptsched_dir = Path(rptsched_dir)
    if today is None:
        today = datetime.now()
    threshold = years_before(today, years)
    compiled_regexes = [re.compile(pattern, re.IGNORECASE) for pattern in exclude_owner_regexes]

    file_groups = _group_files_by_id(rptsched_dir)

    candidates = {}
    with (rptsched_dir / "schedlist").open() as f:
        for line in f:
            raw_line = line.rstrip("\n")
            if not raw_line.strip():
                continue

            fields = raw_line.split("|")
            template_id, report_source, description, frequency_flag, created, last_run, owner = (
                fields[0], fields[1], fields[2], fields[3], fields[4], fields[5], fields[6]
            )

            if frequency_flag != "n":
                continue
            if _is_excluded_owner(owner, exclude_owners, compiled_regexes):
                continue
            if is_active(activity_index, report_source, description, owner):
                continue
            if _created_within_window(created, threshold):
                continue

            candidates[template_id] = TemplateCandidate(
                id=template_id,
                raw_line=raw_line,
                report_source=report_source,
                description=description,
                owner=owner,
                frequency_flag=frequency_flag,
                created=created,
                last_run=last_run,
                filenames=sorted(file_groups.get(template_id, [])),
            )

    return candidates
