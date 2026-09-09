import re
from pathlib import Path

ID_PATTERN = re.compile(r'^([a-z0-9]{4})\.(.+)$')


def find_orphan_groups(rptsched_dir: Path):
    rptsched_dir = Path(rptsched_dir)
    schedlist_ids = set()

    with (rptsched_dir / "schedlist").open() as f:
        for line in f:
            if not line.strip():
                continue
            schedlist_ids.add(line.split("|")[0])

    groups = {}
    for entry in rptsched_dir.iterdir():
        if not entry.is_file():
            continue
        match = ID_PATTERN.match(entry.name)
        if not match:
            continue
        file_id = match.group(1)
        groups.setdefault(file_id, []).append(entry.name)

    return {file_id: filenames for file_id, filenames in groups.items() if file_id not in schedlist_ids}
