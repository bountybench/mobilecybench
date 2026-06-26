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
fail() { printf '[cleanup][error] %s\n' "$*" >&2; exit 1; }

have_cmd() { command -v "$1" >/dev/null 2>&1; }

compose() {
  if have_cmd docker && docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" "$@"
  elif have_cmd docker-compose; then
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
         "${SCRIPT_DIR}/after_android_dir.txt" \
         "${SCRIPT_DIR}/baseline_subscriptions.txt" \
         "${SCRIPT_DIR}/baseline_notifications.txt" \
         "${SCRIPT_DIR}/apk_hash_baseline.txt" \
         "${SCRIPT_DIR}/device_epoch_baseline.txt" \
         "${SCRIPT_DIR}/device_epoch_baseline_pre_reset.txt" \
         "${SCRIPT_DIR}/exact_alarm_baseline.json" \
         "${SCRIPT_DIR}/last_state.json" \
         "${SCRIPT_DIR}/hydration_state.json" \
         "${SCRIPT_DIR}/last_verification.json" \
         "${SCRIPT_DIR}/prepare_victim_hydration_state.json"; do
  if [[ -f "$f" ]]; then
    rm -f -- "$f"
  fi
done

info "Removing scores"
# Remove score files
for f in "${SCRIPT_DIR}/generic_scores.json" \
         "${SCRIPT_DIR}/redteam_scores.json" \
         "${SCRIPT_DIR}/scores_remote_attacker.json" \
         "${SCRIPT_DIR}/scores.json"; do
  if [[ -f "$f" ]]; then
    rm -f -- "$f"
  fi
done

info "Stopping crash sniffer"
CRASH_SNIFFER_PID_FILE="${SCRIPT_DIR}/crash_sniffer.pid"
if [[ -f "$CRASH_SNIFFER_PID_FILE" ]]; then
  old_pid=$(cat "$CRASH_SNIFFER_PID_FILE" 2>/dev/null || true)
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    kill "$old_pid" 2>/dev/null || true
    wait "$old_pid" 2>/dev/null || true
  fi
  rm -f -- "$CRASH_SNIFFER_PID_FILE"
fi

info "Removing runtime logs"
# Main directory logs (covers crash_sniffer.log via *.log glob)
rm -f -- "${SCRIPT_DIR}"/*.log 2>/dev/null || true
rm -f -- "${SCRIPT_DIR}"/setup_app_apklink.log 2>/dev/null || true
rm -f -- "${SCRIPT_DIR}"/setup_app_source.log 2>/dev/null || true

# Vuln scenario logs
for vuln_dir in "${SCRIPT_DIR}"/vuln_scenarios/*/; do
  if [[ -d "$vuln_dir" ]]; then
    rm -f -- "${vuln_dir}"/*agent_log*.log 2>/dev/null || true
  fi
done

info "Resetting secrets.json to empty placeholders"
# secrets.json is committed (schema documentation); start_runtime.sh fills it
# with random hex per experiment. Reset to placeholders here so next
# experiment regenerates fresh; stale values would let an agent in a
# follow-on experiment pre-read the previous run's "random" topic names.
SECRETS_FILE="${SCRIPT_DIR}/secrets.json"
cat > "$SECRETS_FILE" <<'JSON'
{
  "alice_secret": "",
  "bob_secret": "",
  "charlie_secret": "",
  "topic_private_alice": "",
  "topic_private_bob": "",
  "topic_private_charlie": ""
}
JSON

# baseline_access_control.json is a generated artifact (ntfy_seeding.py); no
# probe consumes it, but ntfy_seeding still writes it. Drop it between runs.
rm -f -- "${SCRIPT_DIR}/baseline_access_control.json"

info "Cleanup complete"
