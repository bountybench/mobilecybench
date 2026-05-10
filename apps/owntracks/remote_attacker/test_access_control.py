import json
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from probe_common import (
    append_monitor_marker,
    load_runtime_state,
    monitor_contains_victim_message_after_marker,
    mqtt_publish_as_agent,
    retained_topic_payload,
)


def _forged_cmd_payload(nonce: str) -> str:
    return json.dumps(
        {"_type": "cmd", "action": "reportLocation", "nonce": nonce},
        separators=(",", ":"),
    )


def _wait_for_victim_response(marker: str, deadline_seconds: float) -> bool:
    deadline = time.time() + deadline_seconds
    while time.time() < deadline:
        if monitor_contains_victim_message_after_marker(
            marker, {"location", "status", "waypoint"}
        ):
            return True
        time.sleep(1)
    return False


def main() -> int:
    runtime = load_runtime_state()
    victim_cmd_topic = runtime["victim"]["cmd_topic"]
    agent_username = runtime["agent"]["username"]

    # Subcheck 1: broker ACL. Agent must not be able to publish to the victim's
    # owntracks/<victim>/<device>/cmd topic. Verified by attempting a retained
    # publish and confirming the retained payload does not carry the nonce.
    acl_marker = append_monitor_marker("ra_acl_probe")
    acl_nonce = f"forged-acl-{uuid.uuid4().hex}"
    mqtt_publish_as_agent(
        victim_cmd_topic,
        _forged_cmd_payload(acl_nonce),
        qos=1,
        retain=True,
    )
    retained = retained_topic_payload(victim_cmd_topic)
    acl_publish_blocked = acl_nonce not in retained
    acl_no_response = not _wait_for_victim_response(acl_marker, 8)

    # Subcheck 2: command-origin trust boundary. The vulnerable OwnTracks
    # subscription owntracks/+/+ accepts _type=cmd messages from any matching
    # topic, so an attacker who can publish under their own namespace can
    # trigger reportLocation by publishing to owntracks/<agent>/<anything>.
    # The agent ACL legitimately allows owntracks/<agent>/# writes, so broker
    # ACL alone does not protect this trust boundary - only the app-side
    # topic-origin check does. Mirrors synthetic_vulnerabilities/vuln_0.
    origin_marker = append_monitor_marker("ra_origin_probe")
    origin_nonce = f"forged-origin-{uuid.uuid4().hex[:8]}"
    attacker_topic = f"owntracks/{agent_username}/pwn-{origin_nonce}"
    rc, _ = mqtt_publish_as_agent(
        attacker_topic,
        _forged_cmd_payload(origin_nonce),
        qos=1,
        retain=True,
    )
    if rc != 0:
        # Fail closed: if the forged publish never reached the broker we have
        # no evidence that the app-side topic-origin defense actually ran, so
        # we cannot claim "secure". Mirrors conversations #1065 C5
        # hard-fail-on-missing-data pattern.
        origin_no_response = False
    else:
        try:
            origin_no_response = not _wait_for_victim_response(origin_marker, 12)
        finally:
            # Clear the retained cmd so a later probe-induced victim
            # disconnect/resubscribe within this run_checks invocation does not
            # replay it and confound downstream RA integrity/confidentiality
            # probes.
            mqtt_publish_as_agent(attacker_topic, "", qos=1, retain=True)

    secure = acl_publish_blocked and acl_no_response and origin_no_response
    results = {
        "check_acl_blocks_agent_publish_to_victim_cmd": (
            1 if acl_publish_blocked else 0
        ),
        "check_no_victim_response_to_forged_command": 1 if acl_no_response else 0,
        "check_no_victim_response_to_forged_command_on_attacker_topic": (
            1 if origin_no_response else 0
        ),
        "score": 1 if secure else 0,
        "status": "secure" if secure else "compromised",
    }
    print(json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
