import re
import subprocess
from datetime import datetime
from pathlib import Path

FINISHED_REPORT_PATTERN = re.compile(r'^(\d{14}) Finished report ([^:]+):"(.*)"$')
TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"


def parse_line(line):
    """
    Parse one Logs/Report/ line. Returns (report_source, description,
    timestamp) for a "Finished report" line, or None for anything else
    (Starting/Adding/mailing lines, Missing parameter file lines, etc.)
    """
    match = FINISHED_REPORT_PATTERN.match(line)
    if not match:
        return None
    timestamp_str, report_source, description = match.groups()
    return report_source, description, datetime.strptime(timestamp_str, TIMESTAMP_FORMAT)


def _read_lines(log_path: Path):
    if log_path.suffix == ".Z":
        proc = subprocess.run(
            ["zcat", str(log_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=True,
        )
        return proc.stdout.splitlines()
    return log_path.read_text(errors="replace").splitlines()


def iter_log_entries(log_path: Path):
    for line in _read_lines(log_path):
        parsed = parse_line(line)
        if parsed is not None:
            yield parsed


def _file_month(log_path: Path):
    digits = log_path.name.split(".")[0]
    if len(digits) == 6:
        return digits
    if len(digits) == 8:
        return digits[:6]
    return None


def find_log_files(logs_report_dir, since=None):
    logs_report_dir = Path(logs_report_dir)
    since_month = since.strftime("%Y%m") if since is not None else None

    files = list(logs_report_dir.glob("*.log")) + list(logs_report_dir.glob("*.log.Z"))
    if since_month is not None:
        files = [f for f in files if (_file_month(f) or "") >= since_month]
    return sorted(files)


def scan_report_logs(logs_report_dir, since=None):
    """
    Scan Logs/Report/*.log and *.log.Z for "Finished report" lines.
    Returns {(report_source, description): most_recent_timestamp}, limited
    to entries at or after `since` when given.
    """
    index = {}
    for log_path in find_log_files(logs_report_dir, since=since):
        for report_source, description, timestamp in iter_log_entries(log_path):
            if since is not None and timestamp < since:
                continue
            key = (report_source, description)
            if key not in index or timestamp > index[key]:
                index[key] = timestamp
    return index
