#!/usr/bin/env python3
import argparse
import sys
from datetime import datetime
from pathlib import Path

import remove_orphans
import remove_stale_templates
import sync_operator_field

DATA_DIR = Path("/software/WYLD/Unicorn/Rptsched/")
QUARANTINE_DIR = Path("/software/WYLD/Nic/Scripts/rptsched-cleanup/quarantine/")

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
        description="Run remove_orphans, remove_stale_templates, and sync_operator_field "
                     "in sequence against the production Rptsched directory."
    )
    parser.add_argument("--execute", action="store_true")
    return parser


def _build_argv(execute):
    argv = ["--data-dir", str(DATA_DIR), "--quarantine-dir", str(QUARANTINE_DIR)]
    if execute:
        argv.append("--execute")
    return argv


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = QUARANTINE_DIR / "run_{}.log".format(timestamp)
    script_argv = _build_argv(args.execute)

    with log_path.open("w") as log_file:
        real_stdout = sys.stdout
        real_stderr = sys.stderr
        sys.stdout = Tee(real_stdout, log_file)
        sys.stderr = Tee(real_stderr, log_file)
        try:
            for name, script_main in SCRIPTS:
                print("=== {} ===".format(name))
                exit_code = script_main(script_argv)
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
