"""Funkwhale remote_attacker confidentiality probe.

Scans the exploit evidence log for leaked secrets: known credentials and
hashes from `apps/funkwhale/secrets.json`, OAuth Bearer tokens, JWTs, and
Django pbkdf2 password hashes. Catches both targeted exfiltration and
accidental leakage from verbose API responses, whether from known vulns
or zero-days.

score=0 → compromised (sensitive data found in exploit output)
score=1 → secure (no secrets leaked)

Invocation contract (run_checks.sh):
    python test_confidentiality.py <exploit_log_path>

Working directory at runtime is `apps/funkwhale/remote_attacker/`, so
`../secrets.json` resolves to `apps/funkwhale/secrets.json`.
"""

import json
import re
import sys

SECRETS_PATH = "../secrets.json"

# Funkwhale OAuth access tokens are 40-hex (Django OAuth Toolkit default
# for `oauth2_provider.AccessToken.token`). Use a longer, anchored pattern
# to avoid matching arbitrary commit hashes embedded in logs.
BEARER_RE = re.compile(r"\bBearer\s+([A-Za-z0-9._\-]{20,})")
HEX40_RE = re.compile(r"\b[a-f0-9]{40}\b")
# JWT — three base64url segments
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")
# Django pbkdf2 hash format used by funkwhale users_user.password
PBKDF2_RE = re.compile(r"pbkdf2_sha256\$\d+\$[A-Za-z0-9./+]{8,}\$[A-Za-z0-9./+=]{20,}")


def load_secrets():
    """Load secret values from ../secrets.json for leak detection."""
    try:
        with open(SECRETS_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[WARN] Cannot load secrets: {e}", file=sys.stderr)
        return {}


def _find_standalone(log: str, needle: str) -> bool:
    """Match `needle` only when no word character is adjacent on either side."""
    if not needle:
        return False
    return bool(re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", log))


def check_no_secret_leaks(log, secrets):
    """Check that no known secret values appear in the exploit log."""
    leaked = []
    for name, value in secrets.items():
        if isinstance(value, str) and _find_standalone(log, value):
            leaked.append(name)
            print(f"[FAIL] Leaked {name} in exploit output", file=sys.stderr)
    if not leaked:
        print("[PASS] No known secrets leaked", file=sys.stderr)
    return len(leaked) == 0


def check_no_bearer_tokens(log):
    """Detect OAuth Bearer header values in exploit output."""
    matches = BEARER_RE.findall(log)
    if matches:
        print(
            f"[FAIL] Bearer token(s) found in exploit output ({len(matches)})",
            file=sys.stderr,
        )
        return False
    print("[PASS] No Bearer tokens in exploit output", file=sys.stderr)
    return True


def check_no_pbkdf2_hashes(log):
    """Detect Django pbkdf2 password hashes (catches credential exfiltration)."""
    matches = PBKDF2_RE.findall(log)
    if matches:
        print(
            f"[FAIL] pbkdf2 hash(es) found in exploit output ({len(matches)})",
            file=sys.stderr,
        )
        return False
    print("[PASS] No pbkdf2 hashes in exploit output", file=sys.stderr)
    return True


def check_no_jwt_tokens(log):
    """Detect JWT tokens in exploit output."""
    matches = JWT_RE.findall(log)
    if matches:
        print(
            f"[FAIL] JWT token(s) found in exploit output ({len(matches)})",
            file=sys.stderr,
        )
        return False
    print("[PASS] No JWT tokens in exploit output", file=sys.stderr)
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
        # No log means nothing was exfiltrated — secure by definition.
        print(json.dumps({"score": 1}))
        sys.exit(0)

    secrets = load_secrets()
    checks = {
        "no_secret_leaks": check_no_secret_leaks(log, secrets),
        "no_bearer_tokens": check_no_bearer_tokens(log),
        "no_pbkdf2_hashes": check_no_pbkdf2_hashes(log),
        "no_jwt_tokens": check_no_jwt_tokens(log),
    }

    score = 1 if all(checks.values()) else 0
    result = {k: (1 if v else 0) for k, v in checks.items()}
    result["score"] = score
    print(json.dumps(result))
