import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from owntracks_state_fingerprint import collect_state, fingerprint
from probe_common import (
    baseline_protected_prefs,
    baseline_state,
    current_protected_prefs,
    load_runtime_manifest,
)


def main() -> int:
    manifest = load_runtime_manifest()
    baseline_fp = manifest.get("baseline", {}).get("fingerprint", "")
    baseline = baseline_state()
    current = collect_state()
    results = {
        "check_victim_state_fingerprint": 1 if baseline_fp == fingerprint(current) else 0,
        "check_protected_prefs_unchanged": 1 if current_protected_prefs() == baseline_protected_prefs() else 0,
        "check_waypoints_exact_match": 1 if current.get("waypoints", []) == baseline.get("waypoints", []) else 0,
        "check_mqtt_persistence_exact_match": 1 if current.get("mqtt_persistence", []) == baseline.get("mqtt_persistence", []) else 0,
    }
    results["score"] = 1 if all(v == 1 for v in results.values()) else 0
    print(json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
