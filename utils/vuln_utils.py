"""Helpers for resolving vulnerability task directories."""

from pathlib import Path

VULN_ROOTS = ("synthetic_vulnerabilities", "zero_day_vulnerabilities")


def get_vuln_output_name(vuln_ref: str) -> str:
    """Return the basename used for APK and verify mount directories."""
    return Path(vuln_ref).name


def _explicit_vuln_dir(app_dir: Path, vuln_ref: str) -> Path | None:
    """Return an explicitly addressed vulnerability directory, if provided."""
    vuln_path = Path(vuln_ref)
    if vuln_path.is_absolute():
        return vuln_path
    if len(vuln_path.parts) > 1:
        return app_dir / vuln_path
    return None


def _format_candidate(app_dir: Path, candidate: Path) -> str:
    """Format a candidate path relative to the app dir when possible."""
    try:
        return candidate.relative_to(app_dir).as_posix()
    except ValueError:
        return str(candidate)


def iter_vuln_dirs(app_dir: Path, vuln_ref: str):
    """Yield candidate task directories for a vulnerability reference."""
    explicit_dir = _explicit_vuln_dir(app_dir, vuln_ref)
    if explicit_dir is not None:
        yield explicit_dir
        return

    for root in VULN_ROOTS:
        yield app_dir / root / vuln_ref


def find_vuln_dir(app_dir: Path, vuln_ref: str) -> Path | None:
    """Return the unique matching vulnerability directory, if any."""
    matches = [
        candidate
        for candidate in iter_vuln_dirs(app_dir, vuln_ref)
        if candidate.is_dir()
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def resolve_vuln_dir(app_dir: Path, vuln_ref: str) -> Path:
    """Resolve a vulnerability reference to a unique task directory."""
    candidates = list(iter_vuln_dirs(app_dir, vuln_ref))
    matches = [candidate for candidate in candidates if candidate.is_dir()]

    if len(matches) == 1:
        return matches[0]

    if matches:
        formatted = ", ".join(_format_candidate(app_dir, match) for match in matches)
        examples = " or ".join(
            f"{root}/{get_vuln_output_name(vuln_ref)}" for root in VULN_ROOTS
        )
        raise ValueError(
            f"Ambiguous vulnerability reference {vuln_ref!r}; matches: {formatted}. "
            f"Re-run with an explicit path such as {examples}."
        )

    raise ValueError(
        f"Vulnerability directory not found: {describe_vuln_candidates(app_dir, vuln_ref)}"
    )


def describe_vuln_candidates(app_dir: Path, vuln_ref: str) -> str:
    """Return a human-readable list of candidate task directories."""
    return ", ".join(str(path) for path in iter_vuln_dirs(app_dir, vuln_ref))
