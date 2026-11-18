"""Applicability helpers for generic probe scripts.

The generic probe config is keyed at subprobe granularity, while the legacy
runner starts probes at category granularity.  These helpers let each generic
probe preserve legacy behavior when no config is present, and skip only the
disabled subchecks when a per-app ``generic_probe_config.json`` exists.
"""

from __future__ import annotations

import json
import os
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

# On-device app-state subprobes, by category. A remote attacker is off-device,
# and the RA lifecycle's `pm clear` (RemoteAttackerOps.run_phase) wipes the
# injected on-device canary after the exploit, so these read a clean replay as
# "modified" and false-fire. Backend/network subprobes (SSRF, secrets,
# availability, container flag/pwned) are not affected and stay enabled.
RA_DISABLED_SUBPROBES: dict[str, frozenset[str]] = {
    "access": frozenset({"app_activity_flag"}),
    "confidentiality": frozenset({"app_flag"}),
    "integrity": frozenset({"app_flag", "app_pwned_file"}),
}


def _ra_exclusions_active() -> bool:
    """True only when the generic suite is running for a remote attacker.

    Both vars are exported by RedTeamWorkflow._run_checks; MCB_RA_GENERIC_PROBES
    is set only when RunnerConfig.ra_generic_probes opted the run in, so the
    frozen RA path and every malicious_app path are unaffected.
    """
    return (
        os.environ.get("MCB_ATTACKER_MODEL") == "remote_attacker"
        and os.environ.get("MCB_RA_GENERIC_PROBES") == "1"
    )


def load_category_applicability(
    category: str, config_path: Path | str = "generic_probe_config.json"
) -> dict[str, bool]:
    """Return result-key applicability for one generic probe category.

    If no ``generic_probe_config.json`` exists, all result keys are enabled to
    preserve the category-level ``metadata.generic_probes`` behavior.
    """

    path = Path(config_path)
    result_keys = CATEGORY_KEYS[category]
    if path.exists():
        config = json.loads(path.read_text(encoding="utf-8"))
        raw_applicability = config.get("generic_probe_applicability")
        if not isinstance(raw_applicability, dict):
            raise ValueError("generic_probe_applicability must be a dict")

        applicability = {}
        for result_key in result_keys:
            config_key = CONFIG_KEY_BY_RESULT_KEY.get((category, result_key))
            # Result keys without a config key are legacy-only and should not
            # run when an explicit v1 config is present.
            applicability[result_key] = (
                bool(raw_applicability.get(config_key, False)) if config_key else False
            )
    else:
        applicability = {key: True for key in result_keys}

    if _ra_exclusions_active():
        for result_key in RA_DISABLED_SUBPROBES.get(category, ()):
            applicability[result_key] = False

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
