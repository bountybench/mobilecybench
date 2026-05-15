import os
from pathlib import Path


def relative_artifact_path(
    path_value: str | Path | None, artifact_root: Path
) -> str | None:
    """Return an artifact path relative to the artifact bundle root."""
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
