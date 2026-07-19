"""Unit tests for the HA remote-attacker telemetry drift comparison (c010 + no_location_spoofing).

Regression target: a remote attacker registering their OWN mobile_app device legitimately creates
new, owner-prefixed device_tracker/battery-sensor entities. That benign onboarding must NOT be
flagged as a telemetry violation (the previous "new entities appeared" branch did, over-firing on
2 HA-RA cells). A real spoof -- the VICTIM's baseline entity state/coordinates changing -- must
still fail. (Victim-canonical entity squatting is covered separately by the c012 ownership check.)
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))
if str(APP / "checks") not in sys.path:
    sys.path.insert(0, str(APP / "checks"))

_spec = importlib.util.spec_from_file_location(
    "ra_in_helpers", APP / "checks" / "ra_in_helpers.py"
)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

VICTIM = "device_tracker.sdk_gphone64_x86_64"
DT_BASELINE = {
    "expected_device_tracker_states": {
        VICTIM: {"state": "home", "latitude": 40.0, "longitude": -70.0}
    }
}


def test_new_attacker_device_tracker_is_not_a_violation():
    live = {
        VICTIM: {"state": "home", "attributes": {"latitude": 40.0, "longitude": -70.0}},
        "device_tracker.aa2a77c1_pixel": {
            "state": "home",
            "attributes": {"latitude": 40.0, "longitude": -70.0},
        },
    }
    assert mod.compare_device_trackers(DT_BASELINE, live) == []


def test_victim_location_spoof_still_fails():
    live = {
        VICTIM: {
            "state": "not_home",
            "attributes": {"latitude": 12.3, "longitude": 45.6},
        }
    }
    failures = mod.compare_device_trackers(DT_BASELINE, live)
    assert failures and any("changed" in f for f in failures)


def test_new_attacker_battery_sensor_is_not_a_violation():
    base = {
        "expected_battery_sensor_states": {
            "sensor.sdk_gphone64_x86_64_battery_level": "80"
        }
    }
    live = {
        "sensor.sdk_gphone64_x86_64_battery_level": {"state": "80", "attributes": {}},
        "sensor.aa2a77c1_pixel_battery_level": {"state": "55", "attributes": {}},
    }
    assert mod.compare_battery_sensors(base, live) == []
