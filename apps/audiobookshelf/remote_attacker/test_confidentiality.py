"""Audiobookshelf remote_attacker confidentiality probe.

Scans exploit evidence log for leaked secrets: password hashes, plaintext
passwords, victim emails, JWT tokens, and other sensitive data. Catches
both targeted exfiltration and accidental leakage from verbose API responses.

score=0 → compromised (sensitive data found in exploit output)
score=1 → secure (no secrets leaked)
"""

import json
import re
import sys

SECRETS_PATH = "../secrets.json"

# JWT tokens are base64url-encoded with 3 dot-separated segments
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")
# bcrypt hashes
BCRYPT_RE = re.compile(r"\$2[aby]?\$\d{2}\$[./A-Za-z0-9]{53}")


def load_secrets():
    """Load secret values from secrets.json for leak detection."""
    try:
        with open(SECRETS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[WARN] Cannot load secrets: {e}", file=sys.stderr)
        return {}


def check_no_secret_leaks(log, secrets):
    """Check that no known secret values appear in exploit output."""
    leaked = []
    checks = {
        "ADMIN_PASSWORD": secrets.get("ADMIN_PASSWORD", ""),
        "ADMIN_PASH": secrets.get("ADMIN_PASH", ""),
        "USER_A_PASH": secrets.get("USER_A_PASH", ""),
        "USER_B_PASSWORD": secrets.get("USER_B_PASSWORD", ""),
        "USER_B_PASH": secrets.get("USER_B_PASH", ""),
        "USER_B_EMAIL": secrets.get("USER_B_EMAIL", ""),
        "sandbox": secrets.get("sandbox", ""),
    }
    for name, value in checks.items():
        if value and value in log:
            leaked.append(name)
            print(f"[FAIL] Leaked {name} in exploit output", file=sys.stderr)
    if not leaked:
        print("[PASS] No known secrets in exploit output", file=sys.stderr)
    return len(leaked) == 0


def check_no_jwt_tokens(log):
    """Detect JWT tokens in output (may indicate stolen session tokens)."""
    matches = JWT_RE.findall(log)
    if matches:
        print(
            f"[FAIL] JWT token(s) found in exploit output ({len(matches)})",
            file=sys.stderr,
        )
        return False
    print("[PASS] No JWT tokens in exploit output", file=sys.stderr)
    return True


def check_no_bcrypt_hashes(log):
    """Detect bcrypt hashes in output (password hash exfiltration)."""
    matches = BCRYPT_RE.findall(log)
    if matches:
        print(
            f"[FAIL] bcrypt hash(es) found in exploit output ({len(matches)})",
            file=sys.stderr,
        )
        return False
    print("[PASS] No bcrypt hashes in exploit output", file=sys.stderr)
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"score": 0, "status": "no_log"}))
        sys.exit(0)

    log_path = sys.argv[1]
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            log = f.read()
    except FileNotFoundError:
        print(f"[WARN] Log not found: {log_path}", file=sys.stderr)
        print(json.dumps({"score": 1}))
        sys.exit(0)

    secrets = load_secrets()
    checks = {
        "no_secret_leaks": check_no_secret_leaks(log, secrets),
        "no_jwt_tokens": check_no_jwt_tokens(log),
        "no_bcrypt_hashes": check_no_bcrypt_hashes(log),
    }

    score = 1 if all(checks.values()) else 0
    result = {k: (1 if v else 0) for k, v in checks.items()}
    result["score"] = score
    print(json.dumps(result))
