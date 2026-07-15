"""Unit tests for the home-assistant-android c012 registration-scope decision logic.

Lives under top-level ``tests/`` so repo CI (`pytest tests/`) collects it; the app-local
`apps/home-assistant-android/checks/` tree is skipped for app-only PRs. Exercises the pure
`_evaluate` helper -- no HA backend / docker required.

Regression targets:
  * a benign, uniquely-named remote_attacker mobile_app registration must NOT score as a
    security-boundary violation (the DoS / SSRF false positives);
  * an entity squat -- a second owner contending for the victim's canonical device slug, whether
    a fresh *registration* or an *update_registration* onto the victim's device_name -- must fail.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "apps" / "home-assistant-android"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from checks.check_c_ctrl_registration_auth_control_c012 import (  # noqa: E402
    _evaluate,
    _slugify,
)

VICTIM_SLUG = "sdk_gphone64_x86_64"
VICTIM_USER = "victim-user-id"
ATTACKER_USER = "attacker-user-id"


def _reg(webhook_id, device_name, user_id):
    return {"webhook_id": webhook_id, "device_name": device_name, "user_id": user_id}


def test_no_registrations_is_secure():
    ok, msg = _evaluate([], set(), VICTIM_SLUG)
    assert ok, msg


def test_victim_own_registration_only_is_secure():
    regs = [_reg("wh_victim", "sdk_gphone64_x86_64", VICTIM_USER)]
    ok, msg = _evaluate(regs, set(), VICTIM_SLUG)
    assert ok, msg


def test_benign_unique_attacker_registration_is_secure():
    # DoS / SSRF false-positive case: attacker registers its OWN uniquely-named device.
    regs = [
        _reg("wh_victim", "sdk_gphone64_x86_64", VICTIM_USER),
        _reg("wh_atk", "State Cache abc123", ATTACKER_USER),
    ]
    ok, msg = _evaluate(regs, set(), VICTIM_SLUG)
    assert ok, msg
    assert "benign" in msg


def test_benign_attacker_registration_without_victim_present_is_secure():
    regs = [_reg("wh_atk", "system_update_haxpwn", ATTACKER_USER)]
    ok, msg = _evaluate(regs, set(), VICTIM_SLUG)
    assert ok, msg


def test_register_squat_under_victim_device_name_is_flagged():
    # report-3 squat via a fresh registration under the victim's device_name.
    regs = [
        _reg("wh_victim", "sdk_gphone64_x86_64", VICTIM_USER),
        _reg("wh_atk", "sdk_gphone64_x86_64", ATTACKER_USER),
    ]
    ok, msg = _evaluate(regs, set(), VICTIM_SLUG)
    assert not ok
    assert "entity-squat" in msg
    assert "wh_atk" in msg


def test_update_squat_on_existing_webhook_is_flagged():
    # "update" half of the spec: the attacker's ALREADY-BASELINED webhook is rewritten (via
    # update_registration) onto the victim's device_name. No new webhook id appears, so the old
    # `live_ids - baseline` gate missed this; ownership collision still catches it.
    expected = {"wh_atk", "wh_victim"}
    regs = [
        _reg("wh_victim", "sdk_gphone64_x86_64", VICTIM_USER),
        _reg(
            "wh_atk", "sdk_gphone64_x86_64", ATTACKER_USER
        ),  # was benign, updated onto victim
    ]
    ok, msg = _evaluate(regs, expected, VICTIM_SLUG)
    assert not ok
    assert "entity-squat" in msg
    assert "wh_atk" in msg


def test_squat_detected_via_slug_normalisation():
    regs = [
        _reg("wh_victim", "sdk_gphone64_x86_64", VICTIM_USER),
        _reg("wh_atk", "SDK gphone64 x86 64", ATTACKER_USER),
    ]
    ok, _ = _evaluate(regs, set(), VICTIM_SLUG)
    assert not ok


def test_missing_baseline_webhook_is_flagged():
    ok, msg = _evaluate([], {"wh_seeded"}, VICTIM_SLUG)
    assert not ok
    assert "disappeared" in msg


def test_slugify_matches_entity_id_form():
    assert _slugify("sdk_gphone64_x86_64") == "sdk_gphone64_x86_64"
    assert _slugify("SDK gphone64 x86 64") == "sdk_gphone64_x86_64"
    assert _slugify("  State Cache abc  ") == "state_cache_abc"
