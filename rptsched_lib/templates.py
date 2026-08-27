import re
from collections import namedtuple
from datetime import datetime
from pathlib import Path

ID_PATTERN = re.compile(r'^([a-z0-9]{4})\.(.+)$')
NEVER_RUN = "0000000000"
DATETIME_FORMAT = "%Y%m%d%H%M"

TemplateCandidate = namedtuple(
    "TemplateCandidate",
    ["id", "raw_line", "description", "owner", "frequency_flag", "created", "last_run", "filenames"],
)


def _years_before(reference, years):
    try:
        return reference.replace(year=reference.year - years)
    except ValueError:
        # reference is Feb 29 and (year - years) isn't a leap year
        return reference.replace(month=2, day=28, year=reference.year - years)


def _is_stale(created, last_run, threshold):
    if last_run != NEVER_RUN:
        run_date = datetime.strptime(last_run, DATETIME_FORMAT)
    else:
        run_date = datetime.strptime(created, DATETIME_FORMAT)
    return run_date <= threshold


def _group_files_by_id(data_dir: Path):
    groups = {}
    for entry in data_dir.iterdir():
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


def count_manual_templates(data_dir):
    data_dir = Path(data_dir)
    count = 0
    with (data_dir / "schedlist").open() as f:
        for line in f:
            raw_line = line.rstrip("\n")
            if not raw_line.strip():
                continue
            fields = raw_line.split("|")
            if fields[3] == "n":
                count += 1
    return count


def find_stale_template_candidates(data_dir, years=3, today=None, exclude_owners=(), exclude_owner_regexes=()):
    data_dir = Path(data_dir)
    if today is None:
        today = datetime.now()
    threshold = _years_before(today, years)
    compiled_regexes = [re.compile(pattern, re.IGNORECASE) for pattern in exclude_owner_regexes]

    file_groups = _group_files_by_id(data_dir)

    candidates = {}
    with (data_dir / "schedlist").open() as f:
        for line in f:
            raw_line = line.rstrip("\n")
            if not raw_line.strip():
                continue

            fields = raw_line.split("|")
            template_id, description, frequency_flag, created, last_run, owner = (
                fields[0], fields[2], fields[3], fields[4], fields[5], fields[6]
            )

            if frequency_flag != "n":
                continue
            if _is_excluded_owner(owner, exclude_owners, compiled_regexes):
                continue
            if not _is_stale(created, last_run, threshold):
                continue

            candidates[template_id] = TemplateCandidate(
                id=template_id,
                raw_line=raw_line,
                description=description,
                owner=owner,
                frequency_flag=frequency_flag,
                created=created,
                last_run=last_run,
                filenames=sorted(file_groups.get(template_id, [])),
            )

    return candidates
