#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
BASELINE_FILE="${SCRIPT_DIR}/baseline_manifest.json"

info() { printf '[cleanup] %s\n' "$*"; }
warn() { printf '[cleanup][warn] %s\n' "$*" >&2; }

have_cmd() { command -v "$1" >/dev/null 2>&1; }

compose() {
  # Use modern Docker CLI compose subcommand only.
  if have_cmd docker && docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" "$@"
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

# Remove known leftover named volumes if still present
for vol in jerboa_postgres_data jerboa_pictrs_data postgres_data pictrs_data; do
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

# Remove Android internal dir snapshot files
for f in "${SCRIPT_DIR}/baseline_android_dir.txt" "${SCRIPT_DIR}/after_android_dir.txt"; do
  if [[ -f "$f" ]]; then
    info "Removing Android snapshot $f"
    rm -f -- "$f"
  fi
done

# Remove reports and scores for clean runs
if [[ -d "${SCRIPT_DIR}/.reports" ]]; then
  info "Removing reports directory"
  rm -rf -- "${SCRIPT_DIR}/.reports"
fi
if [[ -f "${SCRIPT_DIR}/scores.json" ]]; then
  info "Removing scores.json"
  rm -f -- "${SCRIPT_DIR}/scores.json"
fi

# Remove logs
info "Removing runtime logs"
rm -f -- "${SCRIPT_DIR}"/*agent_log*.log 2>/dev/null || true
rm -f -- "${SCRIPT_DIR}"/jerboa_setup.log 2>/dev/null || true
rm -f -- "${SCRIPT_DIR}"/setup_app_apklink.log 2>/dev/null || true
rm -f -- "${SCRIPT_DIR}"/setup_app_source.log 2>/dev/null || true

# Remove virtual environment
if [[ -d "${SCRIPT_DIR}/.venv" ]]; then
  info "Removing Python virtual environment"
  rm -rf -- "${SCRIPT_DIR}/.venv"
fi

info "Cleanup complete"
