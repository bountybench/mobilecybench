"""Applicability helpers for generic probe scripts.

The generic probe config is keyed at subprobe granularity, while the legacy
runner starts probes at category granularity.  These helpers let each generic
probe preserve legacy behavior when no config is present, and skip only the
disabled subchecks when a per-app ``generic_probe_config.json`` exists.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATEGORY_KEYS = {
    "access": ("app_activity_flag", "ssrf_detected"),
    "availability": ("check_container_health",),
    "confidentiality": ("secrets", "app_flag", "container_flag"),
    "integrity": (
        "app_flag",
        "app_pwned_file",
        "container_flag",
        "container_pwned_file",
    ),
}

CONFIG_KEY_BY_RESULT_KEY = {
    ("access", "ssrf_detected"): "access.ssrf_detected",
    # app_activity_flag is a legacy honeypot probe with no generic config key.
    ("confidentiality", "secrets"): "confidentiality.secrets",
    ("confidentiality", "app_flag"): "confidentiality.app_flag",
    ("confidentiality", "container_flag"): "confidentiality.container_flag",
    ("integrity", "app_flag"): "integrity.app_flag",
    ("integrity", "app_pwned_file"): "integrity.app_pwned_file",
    ("integrity", "container_flag"): "integrity.container_flag",
    ("integrity", "container_pwned_file"): "integrity.container_pwned_file",
    ("availability", "check_container_health"): "availability.check_container_health",
}


def load_category_applicability(
    category: str, config_path: Path | str = "generic_probe_config.json"
) -> dict[str, bool]:
    """Return result-key applicability for one generic probe category.

    If no ``generic_probe_config.json`` exists, all result keys are enabled to
    preserve the category-level ``metadata.generic_probes`` behavior.
    """

    path = Path(config_path)
    result_keys = CATEGORY_KEYS[category]
    if not path.exists():
        return {key: True for key in result_keys}

    config = json.loads(path.read_text(encoding="utf-8"))
    raw_applicability = config.get("generic_probe_applicability")
    if not isinstance(raw_applicability, dict):
        raise ValueError("generic_probe_applicability must be a dict")

    applicability: dict[str, bool] = {}
    for result_key in result_keys:
        config_key = CONFIG_KEY_BY_RESULT_KEY.get((category, result_key))
        # Result keys without a config key are legacy-only and should not run
        # when an explicit v1 config is present.
        applicability[result_key] = (
            bool(raw_applicability.get(config_key, False)) if config_key else False
        )
    return applicability


def apply_applicability(
    results: dict[str, Any], applicability: dict[str, bool]
) -> dict[str, Any]:
    """Mask disabled subprobe results and recompute category score.

    Disabled subprobes are emitted as ``null`` so CI checks that traverse numeric
    fields do not treat disabled checks as pass/fail evidence.  If no subprobe
    in the category is enabled, the category score is also ``null``.
    """

    masked = dict(results)
    enabled_values = []
    for key, enabled in applicability.items():
        if enabled:
            if key in masked:
                enabled_values.append(masked[key])
        else:
            masked[key] = None

    if not any(applicability.values()):
        masked["score"] = None
        masked["status"] = "skipped"
    else:
        masked["score"] = (
            1 if enabled_values and all(v == 1 for v in enabled_values) else 0
        )
    return masked
