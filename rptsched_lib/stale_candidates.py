from datetime import datetime

from rptsched_lib.activity_index import build_activity_index
from rptsched_lib.hist_log import find_hist_files
from rptsched_lib.report_log import find_log_files
from rptsched_lib.templates import find_stale_template_candidates, years_before


class EmptyLogDirectoryError(RuntimeError):
    pass


def _ensure_log_dirs_not_empty(logs_report_dir, logs_hist_dir, years, threshold):
    # A wrong/unmounted/mistyped path would otherwise silently glob() to
    # nothing, making every manual template look inactive -- the same
    # failure shape as the incident the log-based redesign exists to
    # fix, just triggered by a bad path instead of a bad field.
    if not find_log_files(logs_report_dir, since=threshold):
        raise EmptyLogDirectoryError(
            "No files found under logs_report_dir ({}) within the last {} years. "
            "Refusing to proceed -- this would silently make every manual template "
            "look inactive. Check the path.".format(logs_report_dir, years)
        )
    if not find_hist_files(logs_hist_dir, since=threshold):
        raise EmptyLogDirectoryError(
            "No files found under logs_hist_dir ({}) within the last {} years. "
            "Refusing to proceed -- this would silently make every manual template "
            "look inactive. Check the path.".format(logs_hist_dir, years)
        )


def build_index(logs_report_dir, logs_hist_dir, years=3, today=None, index_cache_path=None):
    """
    Just the activity-index half of detection -- what
    build_activity_index_cache.py needs to keep a shared cache fresh
    without doing any candidate selection at all. Shared by
    detect_stale_templates() below, so both raise the same
    EmptyLogDirectoryError under the same conditions.
    """
    if today is None:
        today = datetime.now()
    threshold = years_before(today, years)
    _ensure_log_dirs_not_empty(logs_report_dir, logs_hist_dir, years, threshold)
    return build_activity_index(
        logs_report_dir, logs_hist_dir, since=threshold, cache_path=index_cache_path,
    )


def detect_stale_templates(
    rptsched_dir, logs_report_dir, logs_hist_dir, years=3, today=None,
    exclude_owners=(), exclude_owner_regexes=(),
    exclude_report_sources=(), exclude_report_source_regexes=(),
    index_cache_path=None,
):
    """
    The copy-free core of stale-template detection: builds the activity
    index and returns the stale-candidate dict, against whatever
    rptsched_dir/log dirs it's given -- live or a copy, this function doesn't
    know or care. detect_stale_templates.py's CLI copies rptsched_dir first;
    execute_stale_templates.py calls this directly against live rptsched_dir
    for its pre-mutation re-verification, since it's about to mutate that
    same directory anyway and copying it first would be a wasted second
    copy immediately before the real one.

    Raises EmptyLogDirectoryError if either log dir has no files within
    `years` -- see build_index().
    """
    if today is None:
        today = datetime.now()
    threshold = years_before(today, years)
    _ensure_log_dirs_not_empty(logs_report_dir, logs_hist_dir, years, threshold)

    activity_index = build_activity_index(
        logs_report_dir, logs_hist_dir, since=threshold, cache_path=index_cache_path,
    )

    return find_stale_template_candidates(
        rptsched_dir, activity_index, years=years, today=today,
        exclude_owners=exclude_owners, exclude_owner_regexes=exclude_owner_regexes,
        exclude_report_sources=exclude_report_sources, exclude_report_source_regexes=exclude_report_source_regexes,
    )
