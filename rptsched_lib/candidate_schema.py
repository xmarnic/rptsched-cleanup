STALE_TEMPLATES_SCHEMA_VERSION = 1


def candidate_to_record(c):
    """
    TemplateCandidate -> a JSONL record. last_run is deliberately never
    included -- it isn't part of the removal decision (see
    2026-08-31-remove-stale-templates-log-based-redesign.md) and
    surfacing it anywhere invites the exact misreading that caused the
    production incident that redesign exists to fix.
    """
    return {
        "schema_version": STALE_TEMPLATES_SCHEMA_VERSION,
        "id": c.id,
        "report_source": c.report_source,
        "description": c.description,
        "owner": c.owner,
        "frequency_flag": c.frequency_flag,
        "created": c.created,
        "raw_line": c.raw_line,
        "filenames": c.filenames,
    }
