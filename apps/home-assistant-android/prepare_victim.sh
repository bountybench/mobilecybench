#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# vuln_0 (Deep Link Host Validation Bypass → SSRF) only fires through
# LinkActivity → OnboardingActivity → AuthenticationFragment's WebView, a path
# that is bypassed when HA is already authenticated. The synthetic-vuln
# pipeline runs prepare_app.sh (which handles its own minimal launch) before
# this hook, so skipping here leaves the device in the fresh state the exploit
# expects. vuln_1 and baseline still need the full UI onboarding.
case "${MCB_TASK_ID:-}" in
    vuln_0)
        echo "[INFO] prepare_victim: skipping for ${MCB_TASK_ID} (exploit needs unauthenticated HA)"
        exit 0
        ;;
esac

exec python3 "$SCRIPT_DIR/prepare_victim.py" "$@"
