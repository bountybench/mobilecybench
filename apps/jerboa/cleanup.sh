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

# The harness expects the Android package to be removed by app cleanup.
for pkg in com.jerboa com.jerboa.debug; do
  if adb shell pm list packages 2>/dev/null | grep -q "^package:${pkg}$"; then
    info "Uninstalling $pkg"
    adb uninstall "$pkg" >/dev/null 2>&1 || warn "Failed uninstalling $pkg"
  fi
done

# Remove root-only probe state files if they remain on device
adb shell "su 0 rm -f /data/local/tmp/.mcb_jerboa_probe_auth.json /data/local/tmp/.mcb_jerboa_baseline_fingerprint" >/dev/null 2>&1 || true

# Remove host-side victim marker used by probe identity checks
rm -f -- "/tmp/.mcb_jerboa_victim" 2>/dev/null || true

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
for score_file in "${SCRIPT_DIR}/scores.json" "${SCRIPT_DIR}/generic_scores.json"; do
  if [[ -f "$score_file" ]]; then
    info "Removing $(basename "$score_file")"
    rm -f -- "$score_file"
  fi
done

# Remove generated helper APK/build outputs
for helper_dir in \
  "${SCRIPT_DIR}/helpers/traversal_reproducer/.build" \
  "${SCRIPT_DIR}/helpers/traversal_reproducer/dist"; do
  if [[ -d "$helper_dir" ]]; then
    info "Removing generated helper directory $helper_dir"
    rm -rf -- "$helper_dir"
  fi
done

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
