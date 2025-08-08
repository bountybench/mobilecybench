#!/usr/bin/env bash
# Cleanup script: full teardown of containers, volumes, manifests, and logs.
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
  if have_cmd docker; then
    if docker compose version >/dev/null 2>&1; then
      docker compose -f "$COMPOSE_FILE" "$@"
      return
    fi
  fi
  if have_cmd docker-compose; then
    docker-compose -f "$COMPOSE_FILE" "$@"
    return
  fi
  warn "docker compose not found"
  return 127
}

if [[ -f "$COMPOSE_FILE" ]]; then
  info "Stopping containers and removing volumes"
  compose down --remove-orphans -v || warn "compose down failed"
else
  warn "compose file not found at $COMPOSE_FILE"
fi

# Extra safety: remove known leftover named volumes if still present
for vol in owncloud-android_files files mysql redis; do
  if have_cmd docker && docker volume inspect "$vol" >/dev/null 2>&1; then
    info "Removing leftover volume $vol"
    docker volume rm -f "$vol" >/dev/null 2>&1 || warn "Failed removing volume $vol"
  fi
done

# Remove manifests
if [[ -f "$BASELINE_FILE" ]]; then
  info "Removing baseline manifest $BASELINE_FILE"
  rm -f -- "$BASELINE_FILE"
fi

# Remove logs
info "Removing runtime logs"
rm -f -- "${SCRIPT_DIR}"/*agent_log*.log 2>/dev/null || true
rm -f -- "${SCRIPT_DIR}"/owncloud_setup.log 2>/dev/null || true

info "Cleanup complete"
