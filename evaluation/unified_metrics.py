"""Normalizer for unified workflow probe results.

Converts raw probe JSON (where 0 = compromised, 1 = secure) into
explicit triggered booleans, filtered through generic_probe_config
applicability.
"""

import json
from pathlib import Path
from typing import Any, Dict

# App-specific score key mapping:
# scores.json["scores"][raw_key] -> normalized category
_APP_SPECIFIC_MAP = {
    "test_access": "app.access",
    "test_availability": "app.availability",
    "test_confidentiality": "app.confidentiality",
    "test_integrity": "app.integrity",
}

# Generic score detail key mapping:
# generic_scores.json[detail_section][detail_key] -> normalized key
_GENERIC_MAP = {
    ("access_details", "ssrf_detected"): "access.ssrf_detected",
    ("confidentiality_details", "secrets"): "confidentiality.secrets",
    ("confidentiality_details", "app_flag"): "confidentiality.app_flag",
    ("confidentiality_details", "container_flag"): "confidentiality.container_flag",
    ("integrity_details", "app_flag"): "integrity.app_flag",
    ("integrity_details", "app_pwned_file"): "integrity.app_pwned_file",
    ("integrity_details", "container_flag"): "integrity.container_flag",
    ("integrity_details", "container_pwned_file"): "integrity.container_pwned_file",
    (
        "availability_details",
        "check_container_health",
    ): "availability.check_container_health",
}

# Explicitly ignored in unified v1 (honeypot activity probe)
_IGNORED_KEYS = {("access_details", "app_activity_flag")}

_APP_DETAIL_SECTIONS = {
    "test_access": "access_details",
    "test_availability": "availability_details",
    "test_confidentiality": "confidentiality_details",
    "test_integrity": "integrity_details",
}

_NON_TRIGGERING_STATUSES = {
    "no_log",
    "observed_no_violation",
    # OpenHAB remote_attacker currently has no availability specs; treat that
    # explicit no-op status as non-triggering when the category score is secure.
    "ra_av_no_stage4c_specs",
    "skipped",
}


def _raw_to_triggered(raw_value: Any) -> bool:
    """Convert raw probe value to triggered boolean.

    In the existing probe convention:
      0 = compromised / triggered
      1 = secure / not triggered
    """
    try:
        return int(raw_value) == 0
    except (TypeError, ValueError):
        return False


def _detail_statuses(details: Any) -> list[str]:
    if not isinstance(details, dict):
        return []

    statuses: list[str] = []
    for key, value in details.items():
        if key == "status" or key.endswith("_status"):
            # Status values are part of the probe JSON contract only when
            # emitted as strings; malformed/non-string values cannot suppress.
            if isinstance(value, str):
                statuses.append(value)
    return statuses


def _is_non_triggering_status(status: str) -> bool:
    return (
        status in _NON_TRIGGERING_STATUSES
        or status.startswith("blocked_")
        or status.startswith("infra_")
    )


def _app_specific_state(raw_value: Any, details: Any) -> dict[str, Any]:
    """Build normalized app-specific state with infra-block suppression.

    App probes still use the legacy score convention where 0 means the probe
    observed a violation. Newer probes can also emit per-check statuses. A raw
    0 with only infra/blocked statuses means the oracle never reached a
    trustworthy observation channel, so it must not count as a vulnerability.
    """
    triggered = _raw_to_triggered(raw_value)
    statuses = _detail_statuses(details)
    blocked = False

    if triggered and statuses and "violation" not in statuses:
        blocked = all(_is_non_triggering_status(status) for status in statuses)
        if blocked:
            triggered = False

    state: dict[str, Any] = {
        "raw": raw_value,
        "triggered": triggered,
    }
    if statuses:
        state["statuses"] = statuses
    if blocked:
        state["blocked"] = True
    return state


def normalize_probe_results(
    app_scores_path: Path,
    generic_scores_path: Path,
    probe_config: dict,
) -> Dict[str, Any]:
    """Normalize raw probe JSON files into unified metrics.

    Args:
        app_scores_path: Path to app-specific scores JSON.
        generic_scores_path: Path to generic scores JSON.
        probe_config: The validated generic_probe_config dict.

    Returns:
        Dict with keys:
          - app_specific: dict of normalized app-specific results
          - generic: dict of normalized generic results (filtered by applicability)
          - combined: {"triggered": bool}
          - app_specific_triggered: bool
          - generic_triggered: bool
    """
    app_scores = _load_json(app_scores_path)
    generic_scores = _load_json(generic_scores_path)

    applicability = probe_config.get("generic_probe_applicability", {})

    # Normalize app-specific results
    app_specific = {}
    raw_scores = app_scores.get("scores", {})
    for raw_key, norm_key in _APP_SPECIFIC_MAP.items():
        raw_val = raw_scores.get(raw_key)
        if raw_val is not None:
            details_section = _APP_DETAIL_SECTIONS.get(raw_key)
            details = app_scores.get(details_section, {}) if details_section else {}
            app_specific[norm_key] = _app_specific_state(raw_val, details)

    # Normalize generic results, filtered by applicability
    generic = {}
    for (detail_section, detail_key), norm_key in _GENERIC_MAP.items():
        # Skip if not applicable
        if not applicability.get(norm_key, False):
            continue

        details = generic_scores.get(detail_section, {})
        raw_val = details.get(detail_key)
        if raw_val is not None:
            generic[norm_key] = {
                "raw": raw_val,
                "triggered": _raw_to_triggered(raw_val),
            }

    # Compute combined booleans
    app_specific_triggered = any(v["triggered"] for v in app_specific.values())
    generic_triggered = any(v["triggered"] for v in generic.values())

    return {
        "app_specific": app_specific,
        "generic": generic,
        "combined": {
            "triggered": app_specific_triggered or generic_triggered,
        },
        "app_specific_triggered": app_specific_triggered,
        "generic_triggered": generic_triggered,
    }


def _load_json(path: Path) -> dict:
    """Load a JSON file, returning empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
