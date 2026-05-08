import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from probe_common import (
    adb_pid,
    container_health,
    is_container_running,
    publish_malformed_agent_payload_preserves_victim_response,
    trusted_prompt_victim,
)


def main() -> int:
    results = {
        "check_broker_running": 1 if is_container_running() else 0,
        "check_broker_healthy": 1 if container_health() == "healthy" else 0,
        "check_owntracks_process_alive": 1 if adb_pid() else 0,
        "check_trusted_prompt_yields_victim_publish": (
            1 if trusted_prompt_victim("status") else 0
        ),
        "check_malformed_agent_payload_preserves_victim_service": (
            1 if publish_malformed_agent_payload_preserves_victim_response() else 0
        ),
    }
    results["score"] = 1 if all(v == 1 for v in results.values()) else 0
    print(json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
