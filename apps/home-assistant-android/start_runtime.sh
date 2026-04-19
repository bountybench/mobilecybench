#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "home-assistant-android" "$@")
cd "$SCRIPT_DIR"

install_home_assistant() {
    log_info "Installing Home Assistant APK..."
    adb_install_apk "$APK_PATH"
}

launch_home_assistant() {
    log_info "Launching Home Assistant..."
    adb shell pm grant io.homeassistant.companion.android android.permission.POST_NOTIFICATIONS 2>/dev/null || true
    adb shell monkey -p io.homeassistant.companion.android -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
}

seed_home_assistant_config() {
    log_info "Seeding Home Assistant config..."
    mkdir -p ./config/.storage

    if [ ! -s ./config/configuration.yaml ]; then
        cp ./seeded-files/demo-configuration.yaml ./config/configuration.yaml
    fi

    for file in automations.yaml scripts.yaml scenes.yaml; do
        [ ! -f "./config/$file" ] && echo "[]" > "./config/$file"
    done

    # Auth state MUST be reset on every start_runtime.sh call. The gold-run
    # workflow invokes this once per phase (vulnerable, then clean), but
    # `docker compose down -v` between phases does not remove bind-mount-backed
    # config (./config is a host directory, not a named volume). Without a
    # forced re-seed, refresh tokens minted by the vulnerable-phase exploit
    # persist into ./config/.storage/auth and the clean-phase verify reports
    # VULNERABLE — producing a FALSE POSITIVE verdict.
    cp ./seeded-files/demo-auth ./config/.storage/auth
    cp ./seeded-files/demo-auth_provider.homeassistant ./config/.storage/auth_provider.homeassistant

    if [ -f ./seeded-files/seeded-onboarding-file ]; then
        cp ./seeded-files/seeded-onboarding-file ./config/.storage/onboarding
    fi
}

wait_for_container_healthy() {
    wait_healthy home-assistant_tls_proxy 120 || fatal "home-assistant_tls_proxy did not become healthy"
}

main() {
    timeout 300 playwright install chromium || log_warn "Playwright browser install failed"

    log_info "Setting up user accounts and credentials..."
    python3 setup_accounts.py

    seed_home_assistant_config

    docker network create shared_net 2>/dev/null || true
    docker compose up --build -d

    wait_for_container_healthy
    install_home_assistant
    launch_home_assistant
}

main "$@"
