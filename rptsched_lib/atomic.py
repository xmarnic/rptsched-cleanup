import os
import shutil
import tempfile
from pathlib import Path


def atomic_write(path, content):
    """
    Write `content` (a full string) to `path` via a temp file in the same
    directory, then os.replace -- a crash or failure mid-write never
    leaves `path` partially written. Copies `path`'s existing permissions
    onto the replacement when `path` already exists; skipped for a
    brand-new file (e.g. a cache being written for the first time), since
    there's nothing to copy from.
    """
    path = Path(path)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".{}.".format(path.name), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        if path.exists():
            shutil.copystat(str(path), tmp_path)
        os.replace(tmp_path, str(path))
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
