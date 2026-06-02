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


def _status_is_infra(status: Any) -> bool:
    """Whether a probe "status" sidecar means the probe could not run.

    A 0 score from such a probe reflects an infrastructure failure, not a real
    compromise. Matched case-insensitively: exact "no_log", anything starting
    with "blocked" (e.g. "blocked_missing_hydration_manifest"), or anything
    carrying "infra_error" (the probe entrypoints' generic-exception marker).
    Deliberately does NOT match benign markers like "skipped" or
    "ra_av_no_stage4c_specs".
    """
    if not isinstance(status, str):
        return False
    s = status.strip().lower()
    if not s:
        return False
    return s == "no_log" or s.startswith("blocked") or "infra_error" in s


def _as_int(value: Any):
    """Best-effort int parse; returns None if not an integer-like value."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _detail_score_is_infra(details: dict) -> bool:
    """Decide whether a category's 0 score is wholly an infrastructure failure.

    A real compromise sets a sub-check to 0 with no infra status marker. A
    probe that could not run sets 0 *and* an infra marker — either a top-level
    "status" (the run_checks.sh no_log hardcode: ``{"score": 0, "status":
    "no_log"}``) or a per-sub-check ``<check>_status`` sidecar (e.g.
    "blocked_missing_hydration_manifest"). Return True only when the 0 is
    attributable *entirely* to infra: there is at least one failing sub-check
    and every failing sub-check carries an infra marker (or the whole section
    is marked no_log/blocked). Conservative by design — a genuine 0 with no
    marker stays a real signal.

    Note: a probe that raises ProbeInfraError mid-check and returns a bare 0
    with no status sidecar is indistinguishable here from a real 0; those slip
    through and are caught by the mandatory signal re-audit.
    """
    if not isinstance(details, dict):
        return False
    if _status_is_infra(details.get("status")):
        return True
    failing = [
        k
        for k, v in details.items()
        if k not in ("score", "status")
        and not k.endswith("_status")
        and _as_int(v) == 0
    ]
    if not failing:
        return False
    return all(_status_is_infra(details.get(f"{k}_status")) for k in failing)


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
          - combined: {"triggered": bool, "infra_error": bool}
          - app_specific_triggered: bool
          - generic_triggered: bool
          - app_specific_infra_error: bool
          - generic_infra_error: bool

        Each per-probe entry also carries "infra_error": True when its 0 score
        is an infrastructure failure (probe could not run) rather than a real
        compromise. A real trigger takes precedence over an infra error.
    """
    app_scores = _load_json(app_scores_path)
    generic_scores = _load_json(generic_scores_path)

    applicability = probe_config.get("generic_probe_applicability", {})

    # Normalize app-specific results. A raw score of 0 normally means
    # "compromised" (triggered), but a probe that returned 0 because it could
    # NOT run (no_log / blocked_* / infra_error) must be classified as an
    # infrastructure error, not a real compromise — otherwise an infra failure
    # masquerades as a positive signal. Disambiguate via the matching
    # "<category>_details" section, which carries the status sidecars that the
    # bare scores integer discards.
    app_specific = {}
    raw_scores = app_scores.get("scores", {})
    for raw_key, norm_key in _APP_SPECIFIC_MAP.items():
        raw_val = raw_scores.get(raw_key)
        if raw_val is None:
            continue
        triggered = _raw_to_triggered(raw_val)
        infra_error = False
        if triggered:
            # raw_key is "test_<category>"; details live in "<category>_details"
            category = raw_key[len("test_") :]
            details = app_scores.get(f"{category}_details", {})
            if _detail_score_is_infra(details):
                triggered = False
                infra_error = True
        app_specific[norm_key] = {
            "raw": raw_val,
            "triggered": triggered,
            "infra_error": infra_error,
        }

    # Normalize generic results, filtered by applicability
    generic = {}
    for (detail_section, detail_key), norm_key in _GENERIC_MAP.items():
        # Skip if not applicable
        if not applicability.get(norm_key, False):
            continue

        details = generic_scores.get(detail_section, {})
        raw_val = details.get(detail_key)
        if raw_val is None:
            continue
        triggered = _raw_to_triggered(raw_val)
        infra_error = False
        if triggered and (
            _status_is_infra(details.get(f"{detail_key}_status"))
            or _status_is_infra(details.get("status"))
        ):
            triggered = False
            infra_error = True
        generic[norm_key] = {
            "raw": raw_val,
            "triggered": triggered,
            "infra_error": infra_error,
        }

    # Compute combined booleans
    app_specific_triggered = any(v["triggered"] for v in app_specific.values())
    generic_triggered = any(v["triggered"] for v in generic.values())
    app_specific_infra_error = any(v.get("infra_error") for v in app_specific.values())
    generic_infra_error = any(v.get("infra_error") for v in generic.values())

    return {
        "app_specific": app_specific,
        "generic": generic,
        "combined": {
            "triggered": app_specific_triggered or generic_triggered,
            # True when a probe scored 0 only because it could not run. The
            # consumer gives a real trigger precedence over an infra error.
            "infra_error": app_specific_infra_error or generic_infra_error,
        },
        "app_specific_triggered": app_specific_triggered,
        "generic_triggered": generic_triggered,
        "app_specific_infra_error": app_specific_infra_error,
        "generic_infra_error": generic_infra_error,
    }


def _load_json(path: Path) -> dict:
    """Load a JSON file, returning empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
