from pathlib import Path


def make_rptsched_dir(base_dir: Path, schedlist_lines, extra_files) -> Path:
    """
    Build a rptsched dir at base_dir/rptsched containing a schedlist file
    (one line per entry in schedlist_lines, already pipe-delimited) and
    an empty placeholder file for each name in extra_files.
    Returns the rptsched dir path.
    """
    rptsched_dir = Path(base_dir) / "rptsched"
    rptsched_dir.mkdir(parents=True, exist_ok=True)

    with (rptsched_dir / "schedlist").open("w") as f:
        for line in schedlist_lines:
            f.write(line + "\n")

    for filename in extra_files:
        (rptsched_dir / filename).write_text("placeholder")

    return rptsched_dir
