import bisect
from pathlib import Path

from rptsched_lib.atomic import atomic_write

SCHEDLIST_FILENAME = "schedlist"


def _read_lines(schedlist_path: Path):
    with schedlist_path.open() as f:
        return [line.rstrip("\n") for line in f if line.strip()]


def remove_lines(rptsched_dir, ids_to_remove) -> list:
    rptsched_dir = Path(rptsched_dir)
    schedlist_path = rptsched_dir / SCHEDLIST_FILENAME
    ids_to_remove = set(ids_to_remove)

    remaining = []
    removed = []
    for raw_line in _read_lines(schedlist_path):
        template_id = raw_line.split("|")[0]
        if template_id in ids_to_remove:
            removed.append(raw_line)
        else:
            remaining.append(raw_line)

    atomic_write(schedlist_path, "".join(line + "\n" for line in remaining))
    return removed


def insert_lines(rptsched_dir, lines_to_insert) -> dict:
    rptsched_dir = Path(rptsched_dir)
    schedlist_path = rptsched_dir / SCHEDLIST_FILENAME

    current_lines = _read_lines(schedlist_path)
    current_ids = {line.split("|")[0] for line in current_lines}
    current_keys = [line.split("|")[4] for line in current_lines]

    inserted = 0
    skipped = 0
    for raw_line in lines_to_insert:
        template_id = raw_line.split("|")[0]
        if template_id in current_ids:
            skipped += 1
            continue
        key = raw_line.split("|")[4]
        idx = bisect.bisect_right(current_keys, key)
        current_lines.insert(idx, raw_line)
        current_keys.insert(idx, key)
        current_ids.add(template_id)
        inserted += 1

    atomic_write(schedlist_path, "".join(line + "\n" for line in current_lines))
    return {"inserted": inserted, "skipped": skipped}
