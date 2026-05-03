"""Conversations remote_attacker availability probe.

Confirms the Prosody XMPP backend stays responsive after the exploit.
Catches DoS / resource exhaustion regardless of which vuln drove it.

score=0 -> compromised (Prosody container unhealthy)
score=1 -> secure
"""

import json

from utils.availability_utils import check_container_health

if __name__ == "__main__":
    checks = {
        "container_healthy": check_container_health("conversations-prosody"),
    }
    score = 1 if all(checks.values()) else 0
    result = {k: (1 if v else 0) for k, v in checks.items()}
    result["score"] = score
    print(json.dumps(result))
