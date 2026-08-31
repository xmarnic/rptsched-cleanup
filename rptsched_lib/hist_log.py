import re
import subprocess
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
