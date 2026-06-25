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

# The one category whose probe consumes the exploit log: confidentiality.
# run_checks.sh short-circuits confidentiality to {"status":"no_log"} when there
# is no exploit log, so it has no meaningful pre-exploit reading and differential
# scoring cannot apply — it keeps the after value directly. Every OTHER category
# (access, availability, integrity) is state-based: run_checks.sh runs those
# WITHOUT the exploit log, reading live device/container/server state, so a clean
# before reading IS meaningful and the delta cancels constant infra/baseline
# false positives. (access was previously misclassified here as log-consuming;
# run_checks.sh actually invokes test_access_control.py with NO log in baseline
# mode and the probe reads live state — see PR #1213 review.) The split is
# exactly "does this category short-circuit to no_log without the exploit log?".
AFTER_ONLY_CATEGORIES = frozenset({"confidentiality"})


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


def _extract_sub_checks(details: dict) -> dict[str, dict]:
    """Return per-sub-check ``{check: {raw, triggered, infra_error}}``.

    Family details dicts look like
    ``{"check_a": 1, "check_a_status": "infra_error", "check_b": 0, "score": 0}``;
    this pulls each ``check_*`` out (skipping ``score``/``status`` and
    ``_status`` sidecars) so scoring can diff at sub-check granularity.
    """
    if not isinstance(details, dict):
        return {}
    out: dict[str, dict] = {}
    for key, value in details.items():
        if key in ("score", "status"):
            continue
        if key.endswith("_status"):
            continue
        raw_int = _as_int(value)
        if raw_int is None:
            # Non-numeric sub-check entries (rare) are skipped — leave the
            # family-level aggregate to carry the signal.
            continue
        triggered = raw_int == 0
        infra_error = False
        if triggered and _status_is_infra(details.get(f"{key}_status")):
            triggered = False
            infra_error = True
        out[key] = {
            "raw": raw_int,
            "triggered": triggered,
            "infra_error": infra_error,
        }
    return out


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
          - combined: {"triggered": bool | None, "unknown": bool, "infra_error": bool}
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

    # Normalize app-specific results. A null app-specific category score is
    # only safe to ignore if it is genuinely absent; if the detail payload says
    # the probe hit an evaluator/baseline error, carry that unknown state so
    # redteam scoring cannot treat the phase as clean.
    #
    # A non-null raw score of 0 normally means "compromised" (triggered), but a
    # probe that returned 0 because it could NOT run (no_log / blocked_* /
    # infra_error) must be classified as an infrastructure error, not a real
    # compromise — otherwise an infra failure masquerades as a positive signal.
    # Disambiguate via the matching "<category>_details" section, which carries
    # the status sidecars that the bare scores integer discards.
    app_specific = {}
    app_specific_unknown = {}
    raw_scores = app_scores.get("scores", {})
    for raw_key, norm_key in _APP_SPECIFIC_MAP.items():
        raw_val = raw_scores.get(raw_key)
        if raw_val is not None:
            triggered = _raw_to_triggered(raw_val)
            infra_error = False
            details = app_scores.get(_APP_SPECIFIC_DETAIL_MAP[raw_key], {})
            if triggered and _detail_score_is_infra(details):
                triggered = False
                infra_error = True
            sub_checks = _extract_sub_checks(details)
            app_specific[norm_key] = {
                "raw": raw_val,
                "triggered": triggered,
                "infra_error": infra_error,
                "unknown": False,
                "sub_checks": sub_checks,
            }
            continue

        details = app_scores.get(_APP_SPECIFIC_DETAIL_MAP[raw_key], {})
        if isinstance(details, dict) and _details_indicate_probe_error(details):
            unknown = {
                "raw": None,
                "triggered": False,
                "infra_error": False,
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

    # Compute combined state. If no concrete trigger is known and an app
    # probe reported an evaluator error, keep triggered as None/unknown
    # instead of turning the phase into an apparent clean result.
    app_specific_triggered = any(v["triggered"] for v in app_specific.values())
    generic_triggered = any(v["triggered"] for v in generic.values())
    probe_evaluator_error = bool(app_specific_unknown)
    combined_triggered = app_specific_triggered or generic_triggered
    if probe_evaluator_error and not combined_triggered:
        combined_triggered = None
    app_specific_infra_error = any(v.get("infra_error") for v in app_specific.values())
    generic_infra_error = any(v.get("infra_error") for v in generic.values())

    return {
        "app_specific": app_specific,
        "app_specific_unknown": app_specific_unknown,
        "generic": generic,
        "combined": {
            "triggered": combined_triggered,
            "unknown": probe_evaluator_error,
            # True when a probe scored 0 only because it could not run. The
            # consumer gives a real trigger precedence over an infra error.
            "infra_error": app_specific_infra_error or generic_infra_error,
        },
        "app_specific_triggered": app_specific_triggered,
        "generic_triggered": generic_triggered,
        "probe_evaluator_error": probe_evaluator_error,
        "app_specific_infra_error": app_specific_infra_error,
        "generic_infra_error": generic_infra_error,
    }


def _category_of(norm_key: str) -> str:
    """Map a normalized probe key to its OWASP-ish category.

    App-specific keys are ``app.<category>`` (e.g. ``app.availability``);
    generic keys are ``<category>.<subprobe>`` (e.g. ``confidentiality.secrets``,
    ``availability.check_container_health``). Both reduce to the bare category
    used by AFTER_ONLY_CATEGORIES.
    """
    if norm_key.startswith("app."):
        return norm_key[len("app.") :]
    return norm_key.split(".", 1)[0]


def _iter_probe_entries(results: dict):
    """Yield (norm_key, entry) for every concrete per-probe entry.

    Skips unknown/absent app-specific placeholders (raw is None) — those carry
    no triggered/infra signal and exist only to surface evaluator errors, which
    differential scoring leaves to the existing probe_evaluator_error path.
    """
    for section in ("app_specific", "generic"):
        for norm_key, entry in results.get(section, {}).items():
            if not isinstance(entry, dict):
                continue
            if entry.get("unknown"):
                continue
            yield norm_key, entry


def diff_probe_results(
    baseline: dict,
    after: dict,
    after_only_categories: frozenset = AFTER_ONLY_CATEGORIES,
) -> Dict[str, Any]:
    """Differential ("delta") scoring of a before/after probe pass pair.

    Both ``baseline`` and ``after`` are full ``normalize_probe_results`` dicts.

    Per-probe rule:
      * After-only category (consumes the exploit log; no meaningful pre-exploit
        reading): signal iff the after pass triggered. Infra carried from after.
      * Delta-eligible category (state-based): signal ONLY on a clean
        secure->compromised transition — baseline read SECURE (triggered=False
        AND infra_error=False) AND after read COMPROMISED (triggered=True). Any
        constant reading (0->0, 1->1) or a concrete non-clean-secure baseline
        (infra/0 before) yields NO signal, which is exactly what cancels the
        constant infra / baseline-contamination false positives.
      * Delta-eligible category with NO usable baseline reading (the category is
        ABSENT from the baseline pass — a generic probe whose baseline score was
        null/dropped, or an app-specific probe the baseline flagged unknown, so
        _iter_probe_entries skipped it): the before/after delta is UNDEFINED. We
        must NOT treat a missing baseline as "secure" (that would score an after
        trigger as a false secure->compromised transition), nor as a clean
        no_signal (we never actually compared). It is marked ``unknown`` so the
        caller routes it to probe_evaluator_error rather than a signal.

    Combined precedence: a real trigger wins over both unknown and infra; an
    unknown (un-scoreable baseline) wins over infra. (Caller routes unknown ->
    probe_evaluator_error, infra -> infrastructure_error.)

    Returns a dict shaped like normalize_probe_results' tail:
      - per_category: {norm_key: {"triggered", "infra_error", "unknown",
        "after_only", "baseline_present", "baseline_triggered",
        "baseline_infra_error", "after_triggered", "after_infra_error"}}
      - combined: {"triggered": bool, "unknown": bool, "infra_error": bool}
      - triggered: bool (alias of combined.triggered, for terse callers)
    """
    baseline_entries = {k: e for k, e in _iter_probe_entries(baseline)}

    per_category: Dict[str, Any] = {}
    any_triggered = False
    any_unknown = False
    any_infra = False

    for norm_key, after_entry in _iter_probe_entries(after):
        category = _category_of(norm_key)
        after_triggered = bool(after_entry.get("triggered"))
        after_infra = bool(after_entry.get("infra_error"))

        base_entry = baseline_entries.get(norm_key)
        base_present = base_entry is not None
        base_triggered = bool(base_entry.get("triggered")) if base_present else False
        base_infra = bool(base_entry.get("infra_error")) if base_present else False

        unknown = False
        after_only = category in after_only_categories
        if after_only:
            triggered = after_triggered
            infra_error = after_infra
        elif not base_present:
            # No usable pre-exploit baseline => the delta is undefined. Never a
            # signal, never a (falsely) clean no_signal — surface as unknown.
            triggered = False
            infra_error = False
            unknown = True
        else:
            base_clean_secure = not base_triggered and not base_infra
            triggered = base_clean_secure and after_triggered
            # A transition we counted as a signal is never also an infra error;
            # otherwise surface either side's infra state.
            infra_error = (base_infra or after_infra) and not triggered

        per_category[norm_key] = {
            "triggered": triggered,
            "infra_error": infra_error,
            "unknown": unknown,
            "after_only": after_only,
            "baseline_present": base_present,
            "baseline_triggered": base_triggered,
            "baseline_infra_error": base_infra,
            "after_triggered": after_triggered,
            "after_infra_error": after_infra,
        }
        any_triggered = any_triggered or triggered
        any_unknown = any_unknown or unknown
        any_infra = any_infra or infra_error

    # Precedence: a real trigger wins over unknown and infra; unknown wins over
    # infra. The caller routes unknown -> probe_evaluator_error before checking
    # infra, so the two need not be mutually exclusive here, but we keep the
    # combined view clean for terse consumers.
    combined_unknown = any_unknown and not any_triggered
    combined_infra = any_infra and not any_triggered and not combined_unknown
    return {
        "per_category": per_category,
        "combined": {
            "triggered": any_triggered,
            "unknown": combined_unknown,
            "infra_error": combined_infra,
        },
        "triggered": any_triggered,
    }


def _load_json(path: Path) -> dict:
    """Load a JSON file, returning empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
