"""Writing the tracker's files."""

import os
from pathlib import Path


def write_text(path: Path, text: str) -> None:
    """Write a file whole or not at all: to a temporary file beside it, then moved over it."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text)
    os.replace(temporary, path)
