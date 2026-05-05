import json
import sys

from probe_common import (
    baseline_protected_prefs,
    baseline_state,
    current_protected_prefs,
    query_device_sqlite,
    WAYPOINT_DB_PATH,
)


def main() -> int:
    current = current_protected_prefs()
    baseline = baseline_protected_prefs()
    baseline_waypoints = baseline_state().get("waypoints", [])
    current_waypoints = query_device_sqlite(
        WAYPOINT_DB_PATH,
        "SELECT id, description, geofenceLatitude, geofenceLongitude, geofenceRadius, tst FROM WaypointModel ORDER BY id",
    )
    config_keys = [
        "host",
        "port",
        "username",
        "password",
        "deviceId",
        "clientId",
        "remoteConfiguration",
        "subTopic",
        "pubTopicBase",
        "tls",
        "cmd",
    ]
    results = {
        "check_loadactivity_did_not_mutate_configuration_slice": 1 if {k: current.get(k) for k in config_keys} == {k: baseline.get(k) for k in config_keys} else 0,
        "check_backgroundservice_did_not_change_monitoring": 1 if current.get("monitoring") == baseline.get("monitoring") else 0,
        "check_loadactivity_did_not_mutate_waypoints": 1 if current_waypoints == baseline_waypoints else 0,
    }
    results["score"] = 1 if all(v == 1 for v in results.values()) else 0
    results["status"] = "secure" if results["score"] == 1 else "compromised"
    print(json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
