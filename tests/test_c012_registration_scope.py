"""Unit tests for the home-assistant-android c012 registration-takeover decision logic.

Under top-level ``tests/`` so repo CI (`pytest tests/`) collects it (app-local checks are skipped
for app-only PRs). Exercises the pure ownership parsers + ``_evaluate`` -- no HA backend / docker
required.

Regression targets:
  * a real report-3 squat -- the low-privilege attacker owns the victim's *bare canonical* entity
    -- must fail;
  * a patched build (attacker entities owner-prefixed, bare canonical owned by the victim) and a
    benign uniquely-named registration must both stay secure -- so the check is not reward-hackable
    by merely registering a device, and discriminates vulnerable from patched.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "apps" / "home-assistant-android"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from checks.check_c_ctrl_registration_auth_control_c012 import (  # noqa: E402
    _evaluate,
    _mobile_app_entity_owners,
    _mobile_app_entry_owners,
    _victim_canonical_entity_ids,
)

VICTIM_SLUG = "sdk_gphone64_x86_64"
CANONICAL = _victim_canonical_entity_ids(VICTIM_SLUG)
ATTACKER = "aa2a77c1b4c54f4c9cb50e2e989aff9e"  # nonadminuser
VICTIM = "9b3aa218a2504ba787cdc97a7b022f40"  # testuser
BARE_BATTERY = f"sensor.{VICTIM_SLUG}_battery_level"
BARE_TRACKER = f"device_tracker.{VICTIM_SLUG}"


# --- _evaluate ---------------------------------------------------------------------------
def test_squat_on_bare_canonical_battery_is_flagged():
    ok, msg = _evaluate({BARE_BATTERY: ATTACKER}, CANONICAL, ATTACKER)
    assert not ok
    assert "entity-squat" in msg
    assert BARE_BATTERY in msg


def test_squat_on_bare_canonical_tracker_is_flagged():
    ok, _ = _evaluate({BARE_TRACKER: ATTACKER}, CANONICAL, ATTACKER)
    assert not ok


def test_patched_owner_prefixed_attacker_entity_is_secure():
    # Under the fix the attacker's entities are owner-prefixed and never hold the bare canonical;
    # the bare canonical is owned by the victim.
    owners = {
        f"sensor.{ATTACKER[:8]}_{VICTIM_SLUG}_battery_level": ATTACKER,
        BARE_BATTERY: VICTIM,
        BARE_TRACKER: VICTIM,
    }
    ok, msg = _evaluate(owners, CANONICAL, ATTACKER)
    assert ok, msg


def test_benign_unique_named_attacker_registration_is_secure():
    # DoS/SSRF false-positive case: attacker registers its own uniquely-named device, so its
    # entities live under a different slug; the victim's canonical entities stay victim-owned.
    owners = {
        "sensor.state_cache_abc_battery_level": ATTACKER,
        BARE_BATTERY: VICTIM,
        BARE_TRACKER: VICTIM,
    }
    ok, msg = _evaluate(owners, CANONICAL, ATTACKER)
    assert ok, msg


def test_no_mobile_app_entities_is_secure():
    ok, _ = _evaluate({}, CANONICAL, ATTACKER)
    assert ok


def test_missing_attacker_id_is_error():
    ok, msg = _evaluate({BARE_BATTERY: ATTACKER}, CANONICAL, "")
    assert not ok
    assert "attacker user id unavailable" in msg


# --- ownership parsers -------------------------------------------------------------------
def test_entry_owners_maps_mobile_app_entries_only():
    payload = {
        "data": {
            "entries": [
                {
                    "entry_id": "e1",
                    "domain": "mobile_app",
                    "data": {"user_id": ATTACKER},
                },
                {"entry_id": "e2", "domain": "hue", "data": {"user_id": VICTIM}},
                {"entry_id": "e3", "domain": "mobile_app", "data": {"user_id": VICTIM}},
            ]
        }
    }
    assert _mobile_app_entry_owners(payload) == {"e1": ATTACKER, "e3": VICTIM}


def test_entity_owners_resolves_entity_to_user_via_config_entry():
    registry = {
        "data": {
            "entities": [
                {
                    "entity_id": BARE_BATTERY,
                    "platform": "mobile_app",
                    "config_entry_id": "e1",
                },
                {
                    "entity_id": "sensor.other",
                    "platform": "hue",
                    "config_entry_id": "e2",
                },
                {  # unresolvable config_entry -> dropped
                    "entity_id": "sensor.orphan",
                    "platform": "mobile_app",
                    "config_entry_id": "missing",
                },
            ]
        }
    }
    owners = _mobile_app_entity_owners(registry, {"e1": ATTACKER, "e2": VICTIM})
    assert owners == {BARE_BATTERY: ATTACKER}


def test_parsers_plus_evaluate_end_to_end_squat():
    config = {
        "data": {
            "entries": [
                {
                    "entry_id": "victim",
                    "domain": "mobile_app",
                    "data": {"user_id": VICTIM},
                },
                {
                    "entry_id": "atk",
                    "domain": "mobile_app",
                    "data": {"user_id": ATTACKER},
                },
            ]
        }
    }
    registry = {
        "data": {
            "entities": [
                # attacker's registration won the bare canonical (vulnerable squat)
                {
                    "entity_id": BARE_BATTERY,
                    "platform": "mobile_app",
                    "config_entry_id": "atk",
                },
                # victim displaced to the _2 suffix
                {
                    "entity_id": f"{BARE_BATTERY}_2",
                    "platform": "mobile_app",
                    "config_entry_id": "victim",
                },
            ]
        }
    }
    owners = _mobile_app_entity_owners(registry, _mobile_app_entry_owners(config))
    ok, _ = _evaluate(owners, CANONICAL, ATTACKER)
    assert not ok
