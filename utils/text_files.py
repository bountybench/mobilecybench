"""Tiny helpers for collecting decodable text files.

Lives in utils/ so evaluation/ and workflows/ can both import without one
having to reach across the layer boundary.
"""

from pathlib import Path


def collect_text_files(directory: Path, label_root: Path | None = None) -> list[str]:
    """Return decodable text files under `directory` as labeled `=== rel ===\\n<text>` sections.

    Skips binary blobs (UnicodeDecodeError) and unreadable files (OSError) silently.
    Paths are labeled relative to `label_root or directory`.
    """
    parts: list[str] = []
    if not directory.is_dir():
        return parts
    root = label_root or directory
    for fpath in sorted(directory.rglob("*")):
        if fpath.is_file():
            try:
                text = fpath.read_text(encoding="utf-8", errors="strict")
                parts.append(f"=== {fpath.relative_to(root)} ===\n{text}")
            except (UnicodeDecodeError, OSError):
                pass
    return parts
