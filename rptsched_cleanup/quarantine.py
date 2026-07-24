from pathlib import Path


def make_run_dir(quarantine_dir: Path, prefix: str, timestamp: str) -> Path:
    quarantine_dir = Path(quarantine_dir)
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    run_dir = quarantine_dir / "{}_{}".format(prefix, timestamp)
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir
