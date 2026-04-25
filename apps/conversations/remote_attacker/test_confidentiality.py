"""Conversations remote_attacker confidentiality probe.

Scans the exploit's output log for plaintext static secrets from
secrets.json (admin / testuser / user1 / user2 passwords). Catches
both targeted credential exfiltration and accidental leakage from
verbose XMPP / BOSH responses.

score=0 -> compromised (a known secret appeared in attacker output)
score=1 -> secure
"""

import json
import sys

SECRETS_PATH = "../secrets.json"


def load_secrets():
    try:
        with open(SECRETS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[WARN] Cannot load secrets: {e}", file=sys.stderr)
        return {}


def check_no_secret_leaks(log, secrets):
    leaked = []
    for name, value in secrets.items():
        if value and value in log:
            leaked.append(name)
            print(f"[FAIL] Leaked {name} in exploit output", file=sys.stderr)
    if not leaked:
        print("[PASS] No known secrets in exploit output", file=sys.stderr)
    return len(leaked) == 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"score": 1, "status": "no_log"}))
        sys.exit(0)

    log_path = sys.argv[1]
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            log = f.read()
    except FileNotFoundError:
        print(f"[WARN] Log not found: {log_path}", file=sys.stderr)
        print(json.dumps({"score": 1}))
        sys.exit(0)

    checks = {"no_secret_leaks": check_no_secret_leaks(log, load_secrets())}
    score = 1 if all(checks.values()) else 0
    result = {k: (1 if v else 0) for k, v in checks.items()}
    result["score"] = score
    print(json.dumps(result))
