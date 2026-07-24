from pathlib import Path


def make_data_dir(base_dir: Path, schedlist_lines, extra_files) -> Path:
    """
    Build a data dir at base_dir/rptsched containing a schedlist file
    (one line per entry in schedlist_lines, already pipe-delimited) and
    an empty placeholder file for each name in extra_files.
    Returns the data dir path.
    """
    data_dir = Path(base_dir) / "rptsched"
    data_dir.mkdir(parents=True, exist_ok=True)

    with (data_dir / "schedlist").open("w") as f:
        for line in schedlist_lines:
            f.write(line + "\n")

    for filename in extra_files:
        (data_dir / filename).write_text("placeholder")

    return data_dir
