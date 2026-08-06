import os
import shutil
import tempfile
from pathlib import Path

SCHEDLIST_FILENAME = "schedlist"


def _read_lines(schedlist_path: Path):
    with schedlist_path.open() as f:
        return [line.rstrip("\n") for line in f if line.strip()]


def _atomic_write(schedlist_path: Path, lines):
    fd, tmp_path = tempfile.mkstemp(dir=str(schedlist_path.parent), prefix=".schedlist.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            for line in lines:
                f.write(line + "\n")
        shutil.copystat(str(schedlist_path), tmp_path)
        os.replace(tmp_path, str(schedlist_path))
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def remove_lines(data_dir, ids_to_remove) -> list:
    data_dir = Path(data_dir)
    schedlist_path = data_dir / SCHEDLIST_FILENAME
    ids_to_remove = set(ids_to_remove)

    remaining = []
    removed = []
    for raw_line in _read_lines(schedlist_path):
        template_id = raw_line.split("|")[0]
        if template_id in ids_to_remove:
            removed.append(raw_line)
        else:
            remaining.append(raw_line)

    _atomic_write(schedlist_path, remaining)
    return removed


def insert_lines(data_dir, lines_to_insert) -> dict:
    data_dir = Path(data_dir)
    schedlist_path = data_dir / SCHEDLIST_FILENAME

    current_lines = _read_lines(schedlist_path)
    current_ids = {line.split("|")[0] for line in current_lines}

    inserted = 0
    skipped = 0
    for raw_line in lines_to_insert:
        template_id = raw_line.split("|")[0]
        if template_id in current_ids:
            skipped += 1
            continue
        current_lines.append(raw_line)
        current_ids.add(template_id)
        inserted += 1

    current_lines.sort(key=lambda line: line.split("|")[0])
    _atomic_write(schedlist_path, current_lines)
    return {"inserted": inserted, "skipped": skipped}
