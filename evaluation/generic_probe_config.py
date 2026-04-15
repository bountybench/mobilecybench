"""Loader and validator for per-app generic probe config (unified workflow)."""

import json
from pathlib import Path
from typing import List

GENERIC_PROBE_KEYS = frozenset(
    [
        "access.ssrf_detected",
        "confidentiality.secrets",
        "confidentiality.app_flag",
        "confidentiality.container_flag",
        "integrity.app_flag",
        "integrity.app_pwned_file",
        "integrity.container_flag",
        "integrity.container_pwned_file",
        "availability.check_container_health",
    ]
)

# Probes that require backend containers to be meaningful
_CONTAINER_PROBES = frozenset(
    [
        "access.ssrf_detected",
        "confidentiality.container_flag",
        "integrity.container_flag",
        "integrity.container_pwned_file",
        "availability.check_container_health",
    ]
)

# Probes that require an app_server to be meaningful
_SERVER_PROBES = frozenset(
    [
        "access.ssrf_detected",
    ]
)


class GenericProbeConfigError(ValueError):
    """Raised when generic_probe_config.json is invalid."""


def load_generic_probe_config(
    config_path: Path,
    container_names: list = None,
    app_server: str = None,
) -> dict:
    """Load and validate a generic_probe_config.json file.

    Args:
        config_path: Path to generic_probe_config.json.
        container_names: List of backend container names (from metadata).
        app_server: Backend server address (from metadata).

    Returns:
        The validated config dict.

    Raises:
        GenericProbeConfigError: If the config is invalid.
        FileNotFoundError: If the config file does not exist.
    """
    if not config_path.exists():
        raise FileNotFoundError(f"generic_probe_config.json not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    validate_generic_probe_config(
        config,
        container_names=container_names or [],
        app_server=app_server or "",
    )
    return config


def validate_generic_probe_config(
    config: dict,
    container_names: list = None,
    app_server: str = None,
) -> None:
    """Validate a generic probe config dict.

    Raises GenericProbeConfigError on any issue.
    """
    container_names = container_names or []
    app_server = app_server or ""

    if config.get("version") != 1:
        raise GenericProbeConfigError(
            f"Unsupported generic_probe_config version: {config.get('version')} "
            f"(expected 1)"
        )

    probes = config.get("generic_probe_applicability")
    if not isinstance(probes, dict):
        raise GenericProbeConfigError("generic_probe_applicability must be a dict")

    # Check for unknown keys
    unknown = set(probes.keys()) - GENERIC_PROBE_KEYS
    if unknown:
        raise GenericProbeConfigError(
            f"Unknown probe keys in generic_probe_applicability: {sorted(unknown)}"
        )

    # Check for missing keys
    missing = GENERIC_PROBE_KEYS - set(probes.keys())
    if missing:
        raise GenericProbeConfigError(
            f"Missing probe keys in generic_probe_applicability: {sorted(missing)}"
        )

    # Validate all values are booleans
    for key, value in probes.items():
        if not isinstance(value, bool):
            raise GenericProbeConfigError(
                f"Probe '{key}' must be a boolean, got {type(value).__name__}"
            )

    # Context-dependent validation
    errors: List[str] = []

    has_containers = bool(container_names)
    has_server = bool(app_server)

    if not has_containers:
        for probe_key in _CONTAINER_PROBES:
            if probes.get(probe_key):
                errors.append(f"'{probe_key}' is enabled but container_names is empty")

    if not has_server:
        for probe_key in _SERVER_PROBES:
            if probes.get(probe_key):
                errors.append(f"'{probe_key}' is enabled but app_server is empty")

    if errors:
        raise GenericProbeConfigError(
            "Generic probe config validation errors:\n  - " + "\n  - ".join(errors)
        )
