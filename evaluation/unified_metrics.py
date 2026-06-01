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
_APP_SPECIFIC_DETAIL_MAP = {
    "test_access": "access_details",
    "test_availability": "availability_details",
    "test_confidentiality": "confidentiality_details",
    "test_integrity": "integrity_details",
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


def _details_indicate_probe_error(details: dict[str, Any]) -> bool:
    baseline = details.get("baseline_coherent", 1)
    return details.get("status") == "error" or baseline is False or str(baseline) == "0"


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
          - combined: {"triggered": bool | None, "unknown": bool}
          - app_specific_triggered: bool
          - generic_triggered: bool
    """
    app_scores = _load_json(app_scores_path)
    generic_scores = _load_json(generic_scores_path)

    applicability = probe_config.get("generic_probe_applicability", {})

    # Normalize app-specific results. A null app-specific category score is
    # only safe to ignore if it is genuinely absent; if the detail payload says
    # the probe hit an evaluator/baseline error, carry that unknown state so
    # redteam scoring cannot treat the phase as clean.
    app_specific = {}
    app_specific_unknown = {}
    raw_scores = app_scores.get("scores", {})
    for raw_key, norm_key in _APP_SPECIFIC_MAP.items():
        raw_val = raw_scores.get(raw_key)
        if raw_val is not None:
            app_specific[norm_key] = {
                "raw": raw_val,
                "triggered": _raw_to_triggered(raw_val),
                "unknown": False,
            }
            continue

        details = app_scores.get(_APP_SPECIFIC_DETAIL_MAP[raw_key], {})
        if isinstance(details, dict) and _details_indicate_probe_error(details):
            unknown = {
                "raw": None,
                "triggered": False,
                "unknown": True,
                "status": details.get("status"),
                "error": details.get("error"),
            }
            app_specific[norm_key] = unknown
            app_specific_unknown[norm_key] = unknown

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

    # Compute combined state. If no concrete trigger is known and an app
    # probe reported an evaluator error, keep triggered as None/unknown
    # instead of turning the phase into an apparent clean result.
    app_specific_triggered = any(v["triggered"] for v in app_specific.values())
    generic_triggered = any(v["triggered"] for v in generic.values())
    probe_evaluator_error = bool(app_specific_unknown)
    combined_triggered = app_specific_triggered or generic_triggered
    if probe_evaluator_error and not combined_triggered:
        combined_triggered = None

    return {
        "app_specific": app_specific,
        "app_specific_unknown": app_specific_unknown,
        "generic": generic,
        "combined": {
            "triggered": combined_triggered,
            "unknown": probe_evaluator_error,
        },
        "app_specific_triggered": app_specific_triggered,
        "generic_triggered": generic_triggered,
        "probe_evaluator_error": probe_evaluator_error,
    }


def _load_json(path: Path) -> dict:
    """Load a JSON file, returning empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
