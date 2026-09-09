#!/usr/bin/env python3
import argparse
import sys
from datetime import datetime
from pathlib import Path

import remove_orphans
import remove_stale_templates
import sync_operator_field

SCRIPTS = [
    ("remove_orphans", lambda argv: remove_orphans.main(argv)),
    ("remove_stale_templates", lambda argv: remove_stale_templates.main(argv)),
    ("sync_operator_field", lambda argv: sync_operator_field.main(argv)),
]


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run remove_orphans, remove_stale_templates, and sync_operator_field in sequence."
    )
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--quarantine-dir", required=True, type=Path)
    parser.add_argument(
        "--logs-report-dir", required=True, type=Path,
        help="Forwarded only to remove_stale_templates.",
    )
    parser.add_argument(
        "--logs-hist-dir", required=True, type=Path,
        help="Forwarded only to remove_stale_templates.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--exclude-owner", action="append", default=[], metavar="OWNER",
        help="Forwarded only to remove_stale_templates: exclude templates whose owner "
             "exactly matches OWNER (case-insensitive). Repeatable.",
    )
    parser.add_argument(
        "--exclude-owner-regex", action="append", default=[], metavar="PATTERN",
        help="Forwarded only to remove_stale_templates: exclude templates whose owner "
             "matches regex PATTERN (case-insensitive). Repeatable.",
    )
    return parser


def _build_argv(data_dir, quarantine_dir, execute):
    argv = ["--data-dir", str(data_dir), "--quarantine-dir", str(quarantine_dir)]
    if execute:
        argv.append("--execute")
    return argv


def _build_template_argv(base_argv, logs_report_dir, logs_hist_dir, exclude_owners, exclude_owner_regexes):
    argv = list(base_argv)
    argv.extend(["--logs-report-dir", str(logs_report_dir), "--logs-hist-dir", str(logs_hist_dir)])
    for owner in exclude_owners:
        argv.extend(["--exclude-owner", owner])
    for pattern in exclude_owner_regexes:
        argv.extend(["--exclude-owner-regex", pattern])
    return argv


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    args.quarantine_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = args.quarantine_dir / "run_{}.log".format(timestamp)

    base_argv = _build_argv(args.data_dir, args.quarantine_dir, args.execute)
    script_argvs = {
        "remove_orphans": base_argv,
        "remove_stale_templates": _build_template_argv(
            base_argv, args.logs_report_dir, args.logs_hist_dir, args.exclude_owner, args.exclude_owner_regex,
        ),
        "sync_operator_field": base_argv,
    }

    with log_path.open("w") as log_file:
        real_stdout = sys.stdout
        real_stderr = sys.stderr
        sys.stdout = Tee(real_stdout, log_file)
        sys.stderr = Tee(real_stderr, log_file)
        try:
            for name, script_main in SCRIPTS:
                print("=== {} ===".format(name))
                exit_code = script_main(script_argvs[name])
                print("=== {} exit code: {} ===".format(name, exit_code))
                if exit_code != 0:
                    print("Stopping: {} failed with exit code {}".format(name, exit_code))
                    return exit_code
            print("All scripts completed successfully.")
            return 0
        finally:
            sys.stdout = real_stdout
            sys.stderr = real_stderr


if __name__ == "__main__":
    sys.exit(main())
