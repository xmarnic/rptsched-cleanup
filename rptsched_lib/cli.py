import os
import sys
from pathlib import Path

UNICORN_ROOT_ENV_VAR = "RPTSCHED_UNICORN_ROOT"


def unicorn_root_default():
    """
    Wrapper-level convenience only -- the underlying detect_*/execute_*
    plumbing tools take --data-dir/--logs-report-dir/--logs-hist-dir
    explicitly with no defaults at all, on purpose (no hidden environment
    coupling in the composable pieces). This just reads the env var a
    wrapper's --unicorn-root flag falls back to when not passed.
    """
    return os.environ.get(UNICORN_ROOT_ENV_VAR)


def unicorn_paths(unicorn_root):
    """
    Derive the standard Symphony Unicorn install sub-paths from a root
    directory: data_dir (Rptsched/), logs_report_dir (Logs/Report/),
    logs_hist_dir (Logs/Hist/). This relative structure is Symphony's own
    convention, not a per-site choice -- confirmed by the domain
    reference and specs, which document all three as sharing the exact
    same parent (e.g. /software/WYLD/Unicorn/{Rptsched,Logs/Report,
    Logs/Hist}). The root itself (which site's Unicorn install) is what
    varies and is never hardcoded here.
    """
    root = Path(unicorn_root)
    return root / "Rptsched", root / "Logs" / "Report", root / "Logs" / "Hist"


def run(main_func, argv=None):
    """
    Standard entry point for this project's composable CLI tools. Without
    this, piping stdout into something that closes the pipe early (head,
    less, a downstream tool that only reads part of the stream) makes
    Python print a BrokenPipeError traceback instead of exiting quietly
    like a well-behaved Unix tool -- directly undermining the point of
    building these as pipeable, composable pieces.
    See https://docs.python.org/3/library/signal.html#note-on-sigpipe.
    """
    try:
        exit_code = main_func(argv)
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(1)
    sys.exit(exit_code)
