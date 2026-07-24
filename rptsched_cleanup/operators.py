import csv
import os
import shutil
import tempfile
from collections import namedtuple
from pathlib import Path

OperatorMismatch = namedtuple("OperatorMismatch", ["id", "old_operator", "new_operator"])
SkippedId = namedtuple("SkippedId", ["id", "reason"])


class MissingOperatorLineError(RuntimeError):
    pass


def _extract_operator(set_path):
    with set_path.open() as f:
        for line in f:
            if line.startswith("operator|"):
                fields = line.rstrip("\n").split("|")
                return fields[-2]
    return None


def find_operator_mismatches(data_dir):
    data_dir = Path(data_dir)
    owners = {}
    with (data_dir / "schedlist").open() as f:
        for line in f:
            raw_line = line.rstrip("\n")
            if not raw_line.strip():
                continue
            fields = raw_line.split("|")
            owners[fields[0]] = fields[6]

    mismatches = {}
    skipped = []
    for template_id in sorted(owners):
        owner = owners[template_id]
        set_path = data_dir / "{}.set".format(template_id)
        if not set_path.is_file():
            skipped.append(SkippedId(template_id, "missing .set file"))
            continue

        operator = _extract_operator(set_path)
        if operator is None:
            skipped.append(SkippedId(template_id, "missing operator line"))
            continue

        if operator != owner:
            mismatches[template_id] = OperatorMismatch(template_id, operator, owner)

    return mismatches, skipped


def read_operator(data_dir, template_id):
    set_path = Path(data_dir) / "{}.set".format(template_id)
    if not set_path.is_file():
        return None
    return _extract_operator(set_path)


def _atomic_write(set_path, lines):
    fd, tmp_path = tempfile.mkstemp(dir=str(set_path.parent), prefix=".{}.".format(set_path.name), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            for line in lines:
                f.write(line + "\n")
        shutil.copystat(str(set_path), tmp_path)
        os.replace(tmp_path, str(set_path))
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def rewrite_operator(data_dir, template_id, new_value):
    set_path = Path(data_dir) / "{}.set".format(template_id)

    lines = []
    found = False
    with set_path.open() as f:
        for line in f:
            raw_line = line.rstrip("\n")
            if raw_line.startswith("operator|"):
                fields = raw_line.split("|")
                fields[-2] = new_value
                lines.append("|".join(fields))
                found = True
            else:
                lines.append(raw_line)

    if not found:
        raise MissingOperatorLineError("No operator line found in {}".format(set_path))

    _atomic_write(set_path, lines)


MANIFEST_FIELDS = ["id", "old_operator", "new_operator"]
MANIFEST_FILENAME = "manifest.csv"


class OperatorRewriteError(RuntimeError):
    pass


def write_operator_manifest(run_dir, rows):
    manifest_path = Path(run_dir) / MANIFEST_FILENAME
    with manifest_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return manifest_path


def read_operator_manifest(run_dir):
    manifest_path = Path(run_dir) / MANIFEST_FILENAME
    with manifest_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def apply_mismatches(data_dir, run_dir, mismatches):
    rows = []
    try:
        for template_id in sorted(mismatches):
            m = mismatches[template_id]
            rewrite_operator(data_dir, template_id, m.new_operator)
            rows.append({"id": m.id, "old_operator": m.old_operator, "new_operator": m.new_operator})
    except OSError as err:
        write_operator_manifest(run_dir, rows)
        raise OperatorRewriteError(
            "Failed to rewrite operator field; {} id(s) corrected before the failure: {}".format(len(rows), err)
        ) from err

    write_operator_manifest(run_dir, rows)
    return rows
