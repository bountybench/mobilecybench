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
  info "Stopping containers and removing volumes"
  compose down --remove-orphans -v || warn "compose down failed"
else
  warn "compose file not found at $COMPOSE_FILE"
fi

# Remove manifests
if [[ -f "$BASELINE_FILE" ]]; then
  info "Removing baseline manifest $BASELINE_FILE"
  rm -f -- "$BASELINE_FILE"
fi

# Remove availability baseline
for f in "${SCRIPT_DIR}/baseline_availability.json"; do
  if [[ -f "$f" ]]; then
    info "Removing availability baseline $f"
    rm -f -- "$f"
  fi
done

# Remove Android internal dir snapshot files
for f in "${SCRIPT_DIR}/baseline_android_dir.txt" "${SCRIPT_DIR}/after_android_dir.txt"; do
  if [[ -f "$f" ]]; then
    info "Removing Android snapshot $f"
    rm -f -- "$f"
  fi
done

# Remove integrity baseline files
for f in "${SCRIPT_DIR}/baseline_subscriptions.txt" "${SCRIPT_DIR}/baseline_notifications.txt"; do
  if [[ -f "$f" ]]; then
    info "Removing integrity baseline $f"
    rm -f -- "$f"
  fi
done

# Remove vuln scenario logs
for vuln_dir in "${SCRIPT_DIR}"/vuln_scenarios/*/; do
  if [[ -d "$vuln_dir" ]]; then
    rm -f -- "${vuln_dir}"/*agent_log*.log 2>/dev/null || true
  fi
done

# Remove logs
info "Removing runtime logs"
rm -f -- "${SCRIPT_DIR}"/*agent_log*.log 2>/dev/null || true
rm -f -- "${SCRIPT_DIR}"/setup_app_apklink.log 2>/dev/null || true
rm -f -- "${SCRIPT_DIR}"/setup_app_source.log 2>/dev/null || true

info "Cleanup complete"
