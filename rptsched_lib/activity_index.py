import json
import os
import tempfile
from collections import namedtuple
from datetime import datetime
from pathlib import Path

from rptsched_lib import hist_log, report_log

# datetime.fromisoformat() is 3.7+ only (project is pinned to 3.6.8, see
# CLAUDE.md) -- all timestamps here are always second-precision (no
# microseconds in any source format), so this round-trips isoformat()
# output exactly.
ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"

ActivityIndex = namedtuple("ActivityIndex", ["report_index", "hist_index"])

EMPTY_CACHE = {"report_log": {}, "hist_log": {}}


def is_active(index, report_type, description, owner):
    """
    True if (report_type, description) shows activity in Logs/Report/
    (owner-blind -- this is also what gives every template sharing a
    join key group-level protection for free) or (report_type,
    description, owner) shows activity in Logs/Hist/. Both indices are
    already windowed to the requested --years at build time, so
    presence alone means "active within the window."
    """
    if (report_type, description) in index.report_index:
        return True
    if (report_type, description, owner) in index.hist_index:
        return True
    return False


def _load_cache(cache_path: Path):
    try:
        with cache_path.open() as f:
            cache = json.load(f)
    except (OSError, ValueError):
        return {"report_log": {}, "hist_log": {}}
    cache.setdefault("report_log", {})
    cache.setdefault("hist_log", {})
    return cache


def _save_cache(cache_path: Path, cache):
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(cache_path.parent), prefix=".activity_index.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(cache, f)
        os.replace(tmp_path, str(cache_path))
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def _cached_report_file_entries(log_path: Path, cache):
    key = log_path.name
    mtime = log_path.stat().st_mtime
    cached = cache["report_log"].get(key)
    if cached is not None and cached["mtime"] == mtime:
        return [(rt, desc, datetime.strptime(ts, ISO_FORMAT)) for rt, desc, ts in cached["entries"]]

    entries = list(report_log.iter_log_entries(log_path))
    cache["report_log"][key] = {
        "mtime": mtime,
        "entries": [[rt, desc, ts.strftime(ISO_FORMAT)] for rt, desc, ts in entries],
    }
    return entries


def _cached_hist_file_entries(hist_path: Path, cache):
    key = hist_path.name
    mtime = hist_path.stat().st_mtime
    cached = cache["hist_log"].get(key)
    if cached is not None and cached["mtime"] == mtime:
        return [
            hist_log.HistLogEntry(
                command=row[0],
                timestamp=datetime.strptime(row[1], ISO_FORMAT),
                schedule_id=row[2],
                report_type=row[3],
                description=row[4],
                owner=row[5],
                frequency=row[6],
            )
            for row in cached["entries"]
        ]

    raw_lines = hist_log.filter_raw_lines(hist_log._read_lines(hist_path))
    decoded_text = hist_log.decode(raw_lines)
    entries = hist_log.parse_decoded_records(decoded_text)
    cache["hist_log"][key] = {
        "mtime": mtime,
        "entries": [
            [e.command, e.timestamp.strftime(ISO_FORMAT), e.schedule_id, e.report_type, e.description, e.owner, e.frequency]
            for e in entries
        ],
    }
    return entries


def _build_report_index_cached(logs_report_dir, since, cache):
    index = {}
    for log_path in report_log.find_log_files(logs_report_dir, since=since):
        for rt, desc, ts in _cached_report_file_entries(log_path, cache):
            if ts < since:
                continue
            key = (rt, desc)
            if key not in index or ts > index[key]:
                index[key] = ts
    return index


def _build_hist_index_cached(logs_hist_dir, since, cache):
    index = {}
    for hist_path in hist_log.find_hist_files(logs_hist_dir, since=since):
        for entry in _cached_hist_file_entries(hist_path, cache):
            if entry.timestamp < since or entry.report_type is None or entry.description is None:
                continue
            key = (entry.report_type, entry.description, entry.owner)
            if key not in index or entry.timestamp > index[key]:
                index[key] = entry.timestamp
    return index


def build_activity_index(logs_report_dir, logs_hist_dir, since, cache_path=None):
    """
    Build the merged activity index used by candidate selection. Without
    a cache_path, always does a full rescan (using report_log/hist_log's
    own tested top-level scan functions directly). With a cache_path,
    reuses per-file cached entries when a file's mtime hasn't changed --
    the point that matters for Logs/Hist/, where re-running
    logprint | translate over years of unchanged, already-closed months
    on every invocation would be wasteful.
    """
    if cache_path is None:
        report_index = report_log.scan_report_logs(logs_report_dir, since=since)
        hist_index = hist_log.scan_hist_logs(logs_hist_dir, since=since)
        return ActivityIndex(report_index=report_index, hist_index=hist_index)

    cache_path = Path(cache_path)
    cache = _load_cache(cache_path)
    report_index = _build_report_index_cached(logs_report_dir, since, cache)
    hist_index = _build_hist_index_cached(logs_hist_dir, since, cache)
    _save_cache(cache_path, cache)
    return ActivityIndex(report_index=report_index, hist_index=hist_index)
