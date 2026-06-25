#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "home-assistant-android" "$@")
cd "$SCRIPT_DIR"

# Temporary CI matrix validation change.
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
    log_info "Resetting generated Home Assistant runtime state..."
    if [ -e ./config ]; then
        chmod -R u+w ./config 2>/dev/null || true
        if ! rm -rf ./config 2>/dev/null; then
            docker run --rm -v "$PWD/config:/config" alpine:3.20 \
                sh -c 'find /config -mindepth 1 -maxdepth 1 -exec rm -rf {} +'
            rmdir ./config
        fi
    fi
    mkdir -p ./config/.storage
    rm -f ./config/home-assistant_v2.db*
    rm -f \
        ./config/.storage/core.area_registry \
        ./config/.storage/core.config_entries \
        ./config/.storage/core.device_registry \
        ./config/.storage/core.entity_registry \
        ./config/.storage/core.restore_state

    log_info "Seeding Home Assistant config from source-of-truth files..."
    cp ./seeded-files/demo-configuration.yaml ./config/configuration.yaml

    # Seed automations.yaml / scripts.yaml / scenes.yaml from sentinel
    # templates if they exist; otherwise fall back to the legacy empty list.
    # The sentinel templates are used by Phase A baseline-diff probes (see
    # baseline_manifest.json["expected_automation_entities"] etc.).
    for file in automations.yaml scripts.yaml scenes.yaml; do
        seed_template="./seeded-files/demo-${file}"
        if [ -f "$seed_template" ]; then
            cp "$seed_template" "./config/$file"
        else
            echo "[]" > "./config/$file"
        fi
    done

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
    python3 seed_baseline.py
    install_home_assistant
    launch_home_assistant
}

main "$@"
