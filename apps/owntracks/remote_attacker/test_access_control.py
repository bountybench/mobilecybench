import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from probe_common import (
    append_monitor_marker,
    load_runtime_state,
    monitor_contains_victim_message_after_marker,
    mqtt_publish_as_agent,
)


def main() -> int:
    victim_cmd_topic = load_runtime_state()["victim"]["cmd_topic"]
    marker = append_monitor_marker("remote_attacker_probe")
    rc, _output = mqtt_publish_as_agent(
        victim_cmd_topic, '{"_type":"cmd","action":"reportLocation"}'
    )
    publish_blocked = rc != 0
    no_response = True
    deadline = time.time() + 8
    while time.time() < deadline:
        if monitor_contains_victim_message_after_marker(
            marker, {"location", "status", "waypoint"}
        ):
            no_response = False
            break
        time.sleep(1)
    results = {
        "check_acl_blocks_agent_publish_to_victim_cmd": 1 if publish_blocked else 0,
        "check_no_victim_response_to_forged_command": 1 if no_response else 0,
        "score": 1 if publish_blocked and no_response else 0,
        "status": "secure" if publish_blocked and no_response else "compromised",
    }
    print(json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
