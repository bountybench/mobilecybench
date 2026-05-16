import os
from pathlib import Path


def relative_artifact_path(
    path_value: str | Path | None, artifact_root: Path
) -> str | None:
    """Return ``path_value`` as a POSIX path relative to ``artifact_root``.

    Intended for serializing artifact pointers into ``run_summary.json`` /
    ``redteam_scores.json`` so that an experiment bundle can be moved or
    replayed from a different host. Callers should pass an absolute path that
    lives under ``artifact_root``; an empty/``None`` input yields ``None``,
    and a non-absolute input is returned as-is (resolved against CWD first
    only if it currently exists). On Windows, paths on a different drive than
    ``artifact_root`` cannot be relativized — the original absolute string is
    returned rather than dropping the pointer.
    """
    if not path_value:
        return None

    path = Path(path_value)
    if not path.is_absolute():
        if path.exists():
            path = path.resolve()
        else:
            return path.as_posix()

    try:
        return Path(os.path.relpath(path, artifact_root)).as_posix()
    except ValueError:
        # Different Windows drives cannot be relativized. Keep the original
        # value rather than dropping the artifact pointer entirely.
        return str(path)
