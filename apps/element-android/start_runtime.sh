#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "element-android" "$@")
cd "$SCRIPT_DIR"

mkdir -p synapse-data
docker compose up --build -d

wait_healthy "element-postgres" 120 || fatal "element-postgres did not become healthy"
wait_healthy "element-synapse" 120 || fatal "element-synapse did not become healthy"

log_info "Waiting for user seeding to complete..."
for attempt in $(seq 1 12); do
    seeder_status=$(docker inspect element-seeder --format='{{.State.Status}}' 2>/dev/null || echo "not_found")
    if [[ "$seeder_status" == "exited" ]]; then
        seeder_exit_code=$(docker inspect element-seeder --format='{{.State.ExitCode}}' 2>/dev/null || echo "1")
        [[ "$seeder_exit_code" == "0" ]] && { log_info "User seeding completed!"; break; }
        fatal "User seeding failed (exit code $seeder_exit_code)"
    fi
    [[ $attempt -eq 12 ]] && fatal "User seeding timed out"
    sleep 5
done

log_info "Installing Element Android APK..."
adb_install_apk "$APK_PATH"
log_info "Element Android installed successfully!"
