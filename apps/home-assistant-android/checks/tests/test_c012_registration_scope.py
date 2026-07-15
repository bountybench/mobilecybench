"""Unit tests for the c012 registration-scope decision logic.

Exercises the pure `_evaluate` helper so no HA backend / docker is required. Regression target:
a benign, uniquely-named remote-attacker mobile_app registration must NOT be scored as a
security-boundary violation; only a device_name that impersonates the victim's canonical device
identity under a second owner (an entity squat) may fail.
"""

from __future__ import annotations

from checks.check_c_ctrl_registration_auth_control_c012 import _evaluate, _slugify

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
    # The DoS / SSRF false-positive case: attacker registers its OWN uniquely-named device.
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


def test_squat_under_victim_device_name_is_flagged():
    # Real report-3 squat: a second owner registers under the victim's device_name.
    regs = [
        _reg("wh_victim", "sdk_gphone64_x86_64", VICTIM_USER),
        _reg("wh_atk", "sdk_gphone64_x86_64", ATTACKER_USER),
    ]
    ok, msg = _evaluate(regs, set(), VICTIM_SLUG)
    assert not ok
    assert "entity-squat" in msg
    assert "wh_atk" in msg


def test_squat_detected_via_slug_normalisation():
    # device_name that slugifies onto the victim canonical slug still counts as impersonation.
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
