#!/usr/bin/env bash
# Cleanup script: full teardown of containers, manifests, and logs.
# Usage: ./cleanup.sh
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
BASELINE_FILE="${SCRIPT_DIR}/baseline_manifest.json"

info() { printf '[cleanup] %s\n' "$*"; }
warn() { printf '[cleanup][warn] %s\n' "$*" >&2; }

have_cmd() { command -v "$1" >/dev/null 2>&1; }

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" "$@"
  elif command_exists docker-compose; then
    docker-compose -f "$COMPOSE_FILE" "$@"
  else
    fail "docker compose plugin or docker-compose binary not available"
  fi
}

if [[ -f "$COMPOSE_FILE" ]]; then
  info "Stopping containers"
  # Note: ntfy has no volumes defined, so -v flag is for safety only
  compose down --remove-orphans -v || warn "compose down failed"
else
  warn "compose file not found at $COMPOSE_FILE"
fi

info "Removing baseline files"
# Primary baseline manifest
if [[ -f "$BASELINE_FILE" ]]; then
  rm -f -- "$BASELINE_FILE"
fi

# Auto-generated baseline files
for f in "${SCRIPT_DIR}/baseline_availability.json" \
         "${SCRIPT_DIR}/baseline_android_dir.txt" \
         "${SCRIPT_DIR}/baseline_android_dir_expanded.txt" \
         "${SCRIPT_DIR}/after_android_dir.txt" \
         "${SCRIPT_DIR}/baseline_subscriptions.txt" \
         "${SCRIPT_DIR}/baseline_notifications.txt"; do
  if [[ -f "$f" ]]; then
    rm -f -- "$f"
  fi
done

info "Removing scores"
# Remove score files
for f in "${SCRIPT_DIR}/generic_scores.json" \
         "${SCRIPT_DIR}/scores.json"; do
  if [[ -f "$f" ]]; then
    rm -f -- "$f"
  fi
done

info "Removing runtime logs"
# Main directory logs
rm -f -- "${SCRIPT_DIR}"/*.log 2>/dev/null || true
rm -f -- "${SCRIPT_DIR}"/setup_app_apklink.log 2>/dev/null || true
rm -f -- "${SCRIPT_DIR}"/setup_app_source.log 2>/dev/null || true

# Vuln scenario logs
for vuln_dir in "${SCRIPT_DIR}"/vuln_scenarios/*/; do
  if [[ -d "$vuln_dir" ]]; then
    rm -f -- "${vuln_dir}"/*agent_log*.log 2>/dev/null || true
  fi
done

info "Cleanup complete"