#!/usr/bin/env bash
# Environment + baseline setup script for OwnCloud CIAA tests.
# Steps:
#   1. Verify prerequisites (docker, python3, uv, optional adb)
#   2. Launch docker-compose stack (OwnCloud + DB + Redis)
#   3. Wait for container health
#   4. Create / reuse Python virtual environment via uv
#   5. Ensure Python deps (requests, python-dotenv) present if not declared already
#   6. Run seeder (produces baseline manifest)
#   7. (Optional) Download & install APK (skipped with SKIP_APK=1)
# Usage:
#   ./setup.sh
#   SKIP_APK=1 ./setup.sh                # Skip APK install
#   SEED_OUTPUT=my_manifest.json ./setup.sh
set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
SEED_SCRIPT="${SCRIPT_DIR}/owncloud_setup.py"
APK_LINK_SCRIPT="${SCRIPT_DIR}/setup_app_apklink.sh"
VENV_DIR="${SCRIPT_DIR}/.venv"
DEFAULT_OUTPUT="baseline_manifest.json"
SEED_OUTPUT=${SEED_OUTPUT:-$DEFAULT_OUTPUT}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-180}
HEALTH_INTERVAL=5
LOG_PREFIX="[setup]"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

ensure_uv(){
  if command_exists uv; then return 0; fi
  warn "uv not found; installing (https://astral.sh/uv)"
  command_exists curl || fail "curl required to install uv"
  curl -Ls https://astral.sh/uv/install.sh | sh || fail "uv install failed"
  export PATH="$HOME/.local/bin:$PATH"
  command_exists uv || fail "uv not found after install"
}

ensure_prereqs(){
  info "Checking prerequisites"
  command_exists docker || fail "docker is required"
  command_exists python3 || fail "python3 is required"
  ensure_uv
  info "Prerequisites OK"
}

compose(){
  if command_exists docker && docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" "$@"
  elif command_exists docker-compose; then
    docker-compose -f "$COMPOSE_FILE" "$@"
  else
    fail "docker compose plugin not available"
  fi
}

start_stack(){
  [[ -f "$COMPOSE_FILE" ]] || fail "docker-compose.yml not found at $COMPOSE_FILE"
  info "Starting docker stack"
  compose up -d --remove-orphans
}

wait_for_health(){
  info "Waiting for owncloud_server health (timeout ${HEALTH_TIMEOUT}s)"
  local start; start=$(date +%s)
  while true; do
    local status; status=$(docker inspect --format '{{.State.Health.Status}}' owncloud_server 2>/dev/null || echo "unknown")
    if [[ "$status" == "healthy" ]]; then
      info "ownCloud container healthy"
      break
    fi
    local now; now=$(date +%s)
    if (( now - start > HEALTH_TIMEOUT )); then
      docker ps --format 'table {{.Names}}\t{{.Status}}'
      fail "Timed out waiting for owncloud_server (last status: $status)"
    fi
    sleep "$HEALTH_INTERVAL"
  done
}

setup_python(){
  info "Setting up Python environment via uv"
  cd "$SCRIPT_DIR"
  if [[ ! -d "$VENV_DIR" ]]; then
    uv venv "$VENV_DIR"
  fi
  # shellcheck source=/dev/null
  source "$VENV_DIR/bin/activate"
  if [[ -f uv.lock ]]; then
    uv sync --frozen || fail "uv sync failed"
  elif [[ -f pyproject.toml ]]; then
    # Install declared project + extras
    uv pip install -e . || true
  fi
  ensure_python_deps
  info "Python environment ready"
}

ensure_python_deps(){
  # Minimal deps needed by seeder if not already resolved via pyproject/lock
  local pkgs=(requests python-dotenv)
  for p in "${pkgs[@]}"; do
    python -c "import $p" 2>/dev/null || uv pip install "$p" >/dev/null 2>&1 || fail "Failed installing $p"
  done
}

run_seeder(){
  info "Running seeding script -> $SEED_OUTPUT"
  cd "$SCRIPT_DIR"
  # shellcheck source=/dev/null
  source "$VENV_DIR/bin/activate"
  SEED_OUTPUT_FILE="$SEED_OUTPUT" python3 "$SEED_SCRIPT" || fail "Seeding failed"
  if [[ ! -f "$SEED_OUTPUT" ]]; then
    fail "Expected manifest $SEED_OUTPUT not found"
  fi
  info "Seeder produced $(ls -l "$SEED_OUTPUT" | awk '{print $5" bytes"}')"
}

maybe_install_apk(){
  if [[ "${SKIP_APK:-0}" == "1" ]]; then
    info "Skipping APK installation (SKIP_APK=1)"
    return 0
  fi
  if ! command_exists adb; then
    warn "adb not found; skipping APK installation"
    return 0
  fi
  if [[ -x "$APK_LINK_SCRIPT" ]]; then
    info "Invoking APK link script"
    if ! "$APK_LINK_SCRIPT"; then
      warn "APK link script failed"
      return 0
    fi
  else
    warn "APK link script missing or not executable: $APK_LINK_SCRIPT"
    return 0
  fi
  # Basic verification
  sleep 2
  if adb shell pm list packages | grep -q "com.owncloud.android"; then
    info "APK installed (com.owncloud.android)"
  else
    warn "APK installation not verified"
  fi
}

summary(){
  info "Setup complete"
  info "Manifest: $SEED_OUTPUT"
}

main(){
  ensure_prereqs
  start_stack
  wait_for_health
  setup_python
  run_seeder
  maybe_install_apk
  summary
}

main "$@"
