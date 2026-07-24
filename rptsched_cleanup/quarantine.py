import csv
import shutil
from pathlib import Path


MANIFEST_FIELDS = ["id", "filename", "extension", "source_path", "dest_path", "moved_at"]
MANIFEST_FILENAME = "manifest.csv"


def make_run_dir(quarantine_dir: Path, prefix: str, timestamp: str) -> Path:
    quarantine_dir = Path(quarantine_dir)
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    run_dir = quarantine_dir / "{}_{}".format(prefix, timestamp)
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def write_manifest(run_dir: Path, rows) -> Path:
    manifest_path = Path(run_dir) / MANIFEST_FILENAME
    with manifest_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return manifest_path


def read_manifest(run_dir: Path):
    manifest_path = Path(run_dir) / MANIFEST_FILENAME
    with manifest_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def move_groups_to_quarantine(data_dir: Path, run_dir: Path, groups, moved_at: str):
    data_dir = Path(data_dir)
    run_dir = Path(run_dir)
    rows = []

    for file_id in sorted(groups):
        for filename in sorted(groups[file_id]):
            source_path = data_dir / filename
            dest_path = run_dir / filename
            shutil.move(str(source_path), str(dest_path))

            extension = filename.split(".", 1)[1] if "." in filename else ""
            rows.append({
                "id": file_id,
                "filename": filename,
                "extension": extension,
                "source_path": str(source_path),
                "dest_path": str(dest_path),
                "moved_at": moved_at,
            })

    write_manifest(run_dir, rows)
    return rows
