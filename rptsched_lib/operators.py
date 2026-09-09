from collections import namedtuple
from pathlib import Path

from rptsched_lib.atomic import atomic_write
from rptsched_lib.quarantine import read_manifest, write_manifest

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


def rewrite_operator(data_dir, template_id, new_value):
    set_path = Path(data_dir) / "{}.set".format(template_id)

    lines = []
    found = False
    with set_path.open() as f:
        for line in f:
            raw_line = line.rstrip("\n")
            if not found and raw_line.startswith("operator|"):
                fields = raw_line.split("|")
                fields[-2] = new_value
                lines.append("|".join(fields))
                found = True
            else:
                lines.append(raw_line)

    if not found:
        raise MissingOperatorLineError("No operator line found in {}".format(set_path))

    atomic_write(set_path, "".join(line + "\n" for line in lines))


MANIFEST_FIELDS = ["id", "old_operator", "new_operator"]


class OperatorRewriteError(RuntimeError):
    pass


def write_operator_manifest(run_dir, rows):
    return write_manifest(run_dir, rows, fieldnames=MANIFEST_FIELDS)


def read_operator_manifest(run_dir):
    return read_manifest(run_dir, fieldnames=MANIFEST_FIELDS)


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
