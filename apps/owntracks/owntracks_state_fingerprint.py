from __future__ import annotations

import hashlib
import json
import sys
from typing import Any

from probe_common import (
    MQTT_DB_PATH,
    WAYPOINT_DB_PATH,
    crash_log_state,
    current_protected_prefs,
    query_device_sqlite,
    queue_file_state,
)


def collect_state() -> dict[str, Any]:
    waypoints = query_device_sqlite(
        WAYPOINT_DB_PATH,
        "SELECT id, description, geofenceLatitude, geofenceLongitude, geofenceRadius, tst FROM WaypointModel ORDER BY id",
    )
    mqtt_rows = query_device_sqlite(
        MQTT_DB_PATH,
        "SELECT clientId, length(persistable) AS persistable_size, hex(sha3_256(persistable)) AS persistable_sha256 FROM MqttPersistableForClient ORDER BY clientId",
    )
    if not mqtt_rows:
        mqtt_rows = query_device_sqlite(
            MQTT_DB_PATH,
            "SELECT clientId, length(persistable) AS persistable_size FROM MqttPersistableForClient ORDER BY clientId",
        )
        for row in mqtt_rows:
            row["persistable_sha256"] = ""

    return {
        "protected_prefs": current_protected_prefs(),
        "waypoints": waypoints,
        "mqtt_persistence": mqtt_rows,
        "queue_files": queue_file_state(),
        "crash_log": crash_log_state(),
    }


def fingerprint(state: dict[str, Any]) -> str:
    blob = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def main(argv: list[str]) -> int:
    state = collect_state()
    fp = fingerprint(state)
    if len(argv) > 1 and argv[1] == "fingerprint":
        print(fp)
        return 0
    print(json.dumps({"fingerprint": fp, "state": state}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
