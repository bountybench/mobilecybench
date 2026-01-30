#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "home-assistant-android" "$@")
cd "$SCRIPT_DIR"

install_home_assistant() {
    echo "Installing Home Assistant APK..."
    adb_install_apk "$APK_PATH"
}

launch_home_assistant() {
    echo "Launching Home Assistant..."
    adb shell pm grant io.homeassistant.companion.android.minimal android.permission.POST_NOTIFICATIONS 2>/dev/null || true
    adb shell monkey -p io.homeassistant.companion.android.minimal -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
}

seed_home_assistant_config() {
    echo "Seeding Home Assistant config (if needed)..."
    mkdir -p ./config/.storage

    if [ ! -s ./config/configuration.yaml ]; then
        cp ./seeded-files/demo-configuration.yaml ./config/configuration.yaml
    fi

    for file in automations.yaml scripts.yaml scenes.yaml; do
        [ ! -f "./config/$file" ] && echo "[]" > "./config/$file"
    done

    [ ! -f ./config/.storage/auth ] && cp ./seeded-files/demo-auth ./config/.storage/auth
    [ ! -f ./config/.storage/auth_provider.homeassistant ] && cp ./seeded-files/demo-auth_provider.homeassistant ./config/.storage/auth_provider.homeassistant
    [ -f ./seeded-files/seeded-onboarding-file ] && [ ! -f ./config/.storage/onboarding ] && cp ./seeded-files/seeded-onboarding-file ./config/.storage/onboarding
}

wait_for_container_healthy() {
    local container_name="home-assistant-server"
    local max_wait=120
    local elapsed=0

    echo "Waiting for container '$container_name' to be healthy..."
    while [ $elapsed -lt $max_wait ]; do
        local status=$(docker inspect --format='{{.State.Health.Status}}' "$container_name" 2>/dev/null || echo "unknown")
        [[ "$status" == "healthy" ]] && { echo "Container '$container_name' is healthy!"; return 0; }
        [[ "$status" == "unhealthy" ]] && { echo "[ERROR] Container '$container_name' is unhealthy."; exit 1; }
        sleep 10
        elapsed=$((elapsed + 10))
    done
    echo "[ERROR] Container '$container_name' was not healthy."
    exit 1
}

main() {
    pip install websocket-client playwright 2>/dev/null || true
    timeout 300 playwright install chromium || echo "WARNING: Playwright browser install failed"

    echo "Setting up user accounts and credentials..."
    python3 setup_accounts.py

    seed_home_assistant_config

    docker network create shared_net 2>/dev/null || true
    docker compose up --build -d

    wait_for_container_healthy
    install_home_assistant
    launch_home_assistant
}

main "$@"
