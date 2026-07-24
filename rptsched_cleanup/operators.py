from collections import namedtuple
from pathlib import Path

OperatorMismatch = namedtuple("OperatorMismatch", ["id", "old_operator", "new_operator"])
SkippedId = namedtuple("SkippedId", ["id", "reason"])


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
