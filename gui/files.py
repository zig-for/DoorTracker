"""Writing the tracker's files."""

import os
from pathlib import Path


def write_text(path: Path, text: str) -> None:
    """Write a file whole or not at all: to a temporary file beside it, then moved over it."""
    # Named by process, so two trackers saving the same file do not share it
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(text)
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
