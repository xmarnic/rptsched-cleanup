import re
import subprocess
from collections import namedtuple
from datetime import datetime
from pathlib import Path

# Raw command codes confirmed against real production data (see
# 2026-08-31-report-log-data-sources-and-tagging-roadmap.md): ge=Create
# Scheduled Report, gg=Modify Scheduled Report, gh=Remove Scheduled
# Report, gk=Remove Finished Report, gu=Rename Scheduled Report. go (Set
# Report Options) and all display-only codes are deliberately excluded
# -- they're navigation noise, not usage signal.
RAW_COMMAND_CODE_PATTERN = re.compile(r"\^S\d+g[ehgku]")


def _read_lines(hist_path: Path):
    if hist_path.suffix == ".Z":
        proc = subprocess.run(
            ["zcat", str(hist_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=True,
        )
        return proc.stdout.splitlines()
    return hist_path.read_text(errors="replace").splitlines()


def _file_month(hist_path: Path):
    digits = hist_path.name.split(".")[0]
    if len(digits) == 6:
        return digits
    if len(digits) == 8:
        return digits[:6]
    return None


def find_hist_files(logs_hist_dir, since=None):
    logs_hist_dir = Path(logs_hist_dir)
    since_month = since.strftime("%Y%m") if since is not None else None

    files = list(logs_hist_dir.glob("*.hist")) + list(logs_hist_dir.glob("*.hist.Z"))
    if since_month is not None:
        files = [f for f in files if (_file_month(f) or "") >= since_month]
    return sorted(files)


def filter_raw_lines(lines):
    """
    Pre-filter raw (undecoded) hist lines down to the ones carrying a
    report-schedule command code, so logprint/translate only has to
    decode the small relevant subset instead of the whole mixed
    transaction-type file.
    """
    return [line for line in lines if RAW_COMMAND_CODE_PATTERN.search(line)]


def decode(raw_lines):
    """
    Run the filtered raw lines through Symphony's logprint | translate
    pipeline and return the decoded text. Both are Symphony-specific
    utilities that only exist on the production server -- not available
    in this dev environment, so this function can't be exercised locally
    beyond mocking subprocess.run.
    """
    if not raw_lines:
        return ""
    raw_text = "\n".join(raw_lines) + "\n"
    logprint_out = subprocess.run(
        ["logprint"],
        input=raw_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        check=True,
    ).stdout
    translate_out = subprocess.run(
        ["translate"],
        input=logprint_out,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        check=True,
    ).stdout
    return translate_out


HistLogEntry = namedtuple(
    "HistLogEntry",
    ["command", "timestamp", "schedule_id", "report_type", "description", "owner", "frequency"],
)

HEADER_PATTERN = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{4}),(\d{2}:\d{2}:\d{2}) Station: \S+ Request:.*?Command: (.+)$"
)
TIMESTAMP_FORMAT = "%m/%d/%Y,%H:%M:%S"

# Only these two carry real usage evidence. Modify/Remove Scheduled
# Report carry no report_type/description at all (verified against real
# decoded output); Rename only links a schedule to its own prior
# generation, not back to the manual template that spawned it (see the
# roadmap doc's command vocabulary table).
USAGE_COMMANDS = {"Create Scheduled Report", "Remove Finished Report"}


def _tokenize_fields(detail_text):
    """
    Split a decoded detail line (or several physical lines already
    joined by the caller) into a {label: value} dict. Fields are
    separated by a double space, but values can themselves legitimately
    contain a double space (verified in real data, e.g.
    "scheduled report name:NIOB  FINAL") -- handled by treating any
    double-space-separated token *without* a colon as a continuation of
    the previous field's value, rejoined with the same double space it
    was split on.
    """
    tokens = [t for t in detail_text.split("  ") if t != ""]
    fields = {}
    current_label = None
    for token in tokens:
        if ":" in token:
            label, _, value = token.partition(":")
            fields[label] = value
            current_label = label
        elif current_label is not None:
            fields[current_label] += "  " + token
    return fields


def _parse_block(lines):
    header_match = HEADER_PATTERN.match(lines[0])
    if header_match is None:
        return None

    date_str, time_str, command = header_match.groups()
    if command not in USAGE_COMMANDS:
        return None

    # Some records wrap across more than one physical line, always at a
    # field boundary (verified in real data) -- rejoin with the same
    # double-space field separator before tokenizing.
    detail_text = "  ".join(line.strip() for line in lines[1:])
    fields = _tokenize_fields(detail_text)

    # "login of the owner of the report" is the authoritative owner
    # field but isn't present on every Create Scheduled Report record
    # (verified: present on some, absent on others, with no clean rule
    # found for which). station user's user ID (the acting user) is the
    # reliable fallback.
    owner = fields.get("login of the owner of the report") or fields.get("station user's user ID")

    return HistLogEntry(
        command=command,
        timestamp=datetime.strptime(date_str + "," + time_str, TIMESTAMP_FORMAT),
        schedule_id=fields.get("schedule id"),
        report_type=fields.get("name of run script"),
        description=fields.get("scheduled report name"),
        owner=owner,
        frequency=fields.get("frequency that the report will run"),
    )


def parse_decoded_records(text):
    """
    Parse logprint | translate output into HistLogEntry records for
    Create Scheduled Report and Remove Finished Report only. Skips
    report-boilerplate blocks (the .report/.title/.end banner at the top
    of every logprint run) and any other command type -- both fail the
    header match or the USAGE_COMMANDS check and are silently dropped.
    """
    entries = []
    block = []
    for line in text.splitlines() + [""]:  # trailing sentinel flushes the last block
        if line.strip() == "":
            if block:
                entry = _parse_block(block)
                if entry is not None:
                    entries.append(entry)
                block = []
        else:
            block.append(line)
    return entries


def scan_hist_logs(logs_hist_dir, since=None):
    """
    Scan Logs/Hist/*.hist and *.hist.Z for Create Scheduled Report and
    Remove Finished Report activity. Returns
    {(report_type, description, owner): most_recent_timestamp}, limited
    to entries at or after `since` when given.
    """
    index = {}
    for hist_path in find_hist_files(logs_hist_dir, since=since):
        raw_lines = filter_raw_lines(_read_lines(hist_path))
        decoded_text = decode(raw_lines)
        for entry in parse_decoded_records(decoded_text):
            if since is not None and entry.timestamp < since:
                continue
            if entry.report_type is None or entry.description is None:
                continue
            key = (entry.report_type, entry.description, entry.owner)
            if key not in index or entry.timestamp > index[key]:
                index[key] = entry.timestamp
    return index
