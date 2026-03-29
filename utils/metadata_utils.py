"""Metadata resolution helpers."""


def get_metadata_commit(metadata: dict) -> str:
    """Return the canonical commit from app metadata.

    Prefers ``commit_version``; falls back to legacy ``commit_id``.
    Raises :class:`ValueError` if neither key is present or non-empty.
    """
    commit = metadata.get("commit_version") or metadata.get("commit_id")
    if not commit or not str(commit).strip():
        raise ValueError(
            "metadata.json must define commit_version "
            "(or legacy commit_id for backward compatibility)"
        )
    return str(commit).strip()
