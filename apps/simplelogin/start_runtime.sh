#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "simplelogin" "$@")
cd "$SCRIPT_DIR"

METADATA_FILE="$SCRIPT_DIR/metadata.json"
SECRETS_FILE="$SCRIPT_DIR/secrets.json"

PACKAGE_NAME=$(jq -r '.package_name' "$METADATA_FILE")
TLS_PROXY_CONTAINER=$(jq -r '.container_names[] | select(test("tls_proxy|tls"))' "$METADATA_FILE" | head -n 1)

setup_backend() {
    log_info "Setting up SimpleLogin backend..."

    docker compose down 2>/dev/null || true

    log_info "Starting backend services..."
    docker compose up -d || fatal "Failed to start backend services"

    wait_healthy "$TLS_PROXY_CONTAINER" 180 || fatal "$TLS_PROXY_CONTAINER did not become healthy"
}

seed_test_data() {
    log_info "Seeding test data..."

    if [[ ! -f "$SECRETS_FILE" ]]; then
        fatal "secrets.json not found. This file should be checked into version control."
    fi

    # NOTE: secrets.json is treated as a fixture, not a runtime artifact.
    # Earlier revisions mutated `canary_note` on every start (writing
    # ALIAS_NOTE_<random>) which left git status dirty after each run and
    # made CI re-runs non-idempotent. The committed canary in secrets.json
    # is sufficient for the confidentiality probe (it scans the exploit log
    # for that exact string). Generated artifacts that DO change per-run
    # (baseline_manifest.json, etc.) are produced separately below and are
    # listed in cleanup.sh.

    log_info "Creating users in database..."
    if python3 seed_data.py; then
        log_info "User creation completed"
    else
        fatal "User creation failed — probes depend on seeded users; refusing to continue in degraded mode"
    fi

    log_info "Capturing SimpleLogin passive probe baseline..."
    if python3 simplelogin_probe_lib.py capture-baseline; then
        log_info "Probe baseline captured"
    else
        fatal "Probe baseline capture failed — probes depend on baseline_manifest.json; refusing to continue in degraded mode"
    fi
}

install_app() {
    log_info "Installing SimpleLogin app..."
    adb uninstall "$PACKAGE_NAME" >/dev/null 2>&1 || true
    adb_install_apk "$APK_PATH"
    log_info "App installed successfully"
}

smoke_test() {
    log_info "Launching app..."
    adb shell monkey -p "$PACKAGE_NAME" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
    sleep 3
    if adb shell pidof "$PACKAGE_NAME" >/dev/null 2>&1; then
        log_info "App is running"
    else
        log_warn "App launch verification failed"
    fi
}

main() {
    log_info "Starting SimpleLogin setup..."
    setup_backend
    seed_test_data
    install_app
    smoke_test
    log_info "SimpleLogin setup completed!"
}

main "$@"
