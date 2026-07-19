"""Unit tests for the ntfy malicious_app access-control score decision.

Regression target: a UnifiedPush foreign-app registration is the *designed* distributor<->app flow.
The registration/package-identity checks (unauthorized_up_registration, up_package_mismatch) must not
emit a compromise (score=0) on their own when every substantive access check is clean -- the previous
`all(==1)` rule over-fired on 1 ntfy-MA cell. A real substantive failure (e.g. shareactivity publish
into a victim topic, subscription/notification access) must still emit score=0.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
_spec = importlib.util.spec_from_file_location(
    "ntfy_ac", APP / "test_access_control.py"
)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)
score = mod._compute_access_score

SUBSTANTIVE_CLEAN = {
    "subscription_authorization": 1,
    "notification_access": 1,
    "legitimate_present": 1,
    "linkactivity_filter_bypass": 1,
    "shareactivity_unsupported_publish": 1,
}


def test_registration_only_signal_is_not_a_compromise():
    checks = {
        **SUBSTANTIVE_CLEAN,
        "unauthorized_up_registration": 0,
        "up_package_mismatch": 0,
    }
    assert score(checks) == 1


def test_substantive_failure_still_scores_compromised():
    checks = {
        **SUBSTANTIVE_CLEAN,
        "shareactivity_unsupported_publish": 0,
        "unauthorized_up_registration": 0,
        "up_package_mismatch": 0,
    }
    assert score(checks) == 0


def test_all_clean_is_secure():
    checks = {
        **SUBSTANTIVE_CLEAN,
        "unauthorized_up_registration": 1,
        "up_package_mismatch": 1,
    }
    assert score(checks) == 1


def test_empty_is_zero():
    assert score({}) == 0
