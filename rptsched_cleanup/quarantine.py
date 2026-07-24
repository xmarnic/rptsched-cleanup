import csv
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
