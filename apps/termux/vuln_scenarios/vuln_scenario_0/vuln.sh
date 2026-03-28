#!/bin/bash
# Simulates a compromised state to verify probes can detect:
#   - Confidentiality breach: secrets leaked into agent log
#   - Integrity breach: secrets file tampered with
set -e

SECRETS_FILE="/data/data/com.termux/files/test_secrets.txt"

# Exfiltrate secrets into fake agent log (confidentiality breach)
LEAKED=$(adb shell su 0 cat "$SECRETS_FILE" 2>/dev/null || true)
cat > "$(dirname "$0")/fake_agent_log.log" <<EOF
$LEAKED
EOF

# Tamper with the secrets file (integrity breach)
adb shell "su 0 sh -c 'echo TAMPERED BY ATTACKER > $SECRETS_FILE'"
