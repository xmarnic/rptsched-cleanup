import os
import sys


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
