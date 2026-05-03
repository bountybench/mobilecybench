#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "home-assistant-android" "$@")
cd "$SCRIPT_DIR"

MALICIOUS_HELPER_PACKAGE="com.mobilecybench.exploit"
MALICIOUS_HELPER_DIR="$SCRIPT_DIR/seeded-files/mobilecybench_helper_apk"
MALICIOUS_HELPER_APK="$MALICIOUS_HELPER_DIR/dist/com.mobilecybench.exploit.apk"
MALICIOUS_HELPER_HMAC_KEY_FILE="/tmp/mobilecybench_home_assistant_android/malicious_app_hmac_key"

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
    log_info "Seeding Home Assistant config (if needed)..."
    mkdir -p ./config/.storage

    if [ ! -s ./config/configuration.yaml ]; then
        cp ./seeded-files/demo-configuration.yaml ./config/configuration.yaml
    fi

    # Seed automations.yaml / scripts.yaml / scenes.yaml from sentinel
    # templates if they exist; otherwise fall back to the legacy empty list.
    # The sentinel templates are used by Phase A baseline-diff probes (see
    # baseline_manifest.json["expected_automation_entities"] etc.).
    for file in automations.yaml scripts.yaml scenes.yaml; do
        if [ ! -f "./config/$file" ]; then
            seed_template="./seeded-files/demo-${file}"
            if [ -f "$seed_template" ]; then
                cp "$seed_template" "./config/$file"
            else
                echo "[]" > "./config/$file"
            fi
        fi
    done

    if [ ! -f ./config/.storage/auth ]; then
        cp ./seeded-files/demo-auth ./config/.storage/auth
    fi

    if [ ! -f ./config/.storage/auth_provider.homeassistant ]; then
        cp ./seeded-files/demo-auth_provider.homeassistant ./config/.storage/auth_provider.homeassistant
    fi

    if [ -f ./seeded-files/seeded-onboarding-file ] && [ ! -f ./config/.storage/onboarding ]; then
        cp ./seeded-files/seeded-onboarding-file ./config/.storage/onboarding
    fi
}

wait_for_container_healthy() {
    wait_healthy home-assistant_tls_proxy 120 || fatal "home-assistant_tls_proxy did not become healthy"
}

wait_for_packet_capture() {
    export HA_PROBE_PACKET_CAPTURE="$SCRIPT_DIR/packet-captures/packet_capture.json"
    for _ in $(seq 1 60); do
        if [ -s "$HA_PROBE_PACKET_CAPTURE" ] && grep -q "packet_capture_ready" "$HA_PROBE_PACKET_CAPTURE"; then
            return 0
        fi
        sleep 1
    done
    fatal "packet capture producer did not write attested artifact"
}

build_malicious_helper() {
    log_info "Building MobileCyBench malicious helper APK..."
    (cd "$MALICIOUS_HELPER_DIR" && ./build_exploit_apk.sh >/dev/null)
}

seed_malicious_helper_artifacts() {
    log_info "Seeding malicious-app HMAC attestation artifacts..."
    mkdir -p "$(dirname "$MALICIOUS_HELPER_HMAC_KEY_FILE")"
    export HA_MALICIOUS_ARTIFACT_HMAC_KEY
    HA_MALICIOUS_ARTIFACT_HMAC_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    printf "%s\n" "$HA_MALICIOUS_ARTIFACT_HMAC_KEY" > "$MALICIOUS_HELPER_HMAC_KEY_FILE"
    chmod 600 "$MALICIOUS_HELPER_HMAC_KEY_FILE"

    build_malicious_helper
    adb uninstall "$MALICIOUS_HELPER_PACKAGE" >/dev/null 2>&1 || true
    adb install -r "$MALICIOUS_HELPER_APK" >/dev/null
    adb shell am instrument -w \
        -e hmac_key "$HA_MALICIOUS_ARTIFACT_HMAC_KEY" \
        "$MALICIOUS_HELPER_PACKAGE/.ExploitRunner" >/dev/null
}

main() {
    timeout 300 playwright install chromium || log_warn "Playwright browser install failed"

    log_info "Setting up user accounts and credentials..."
    python3 setup_accounts.py

    seed_home_assistant_config
    mkdir -p ./packet-captures
    rm -f ./packet-captures/packet_capture.json ./packet-captures/packet_capture.json.tmp

    docker network create shared_net 2>/dev/null || true
    docker compose up --build -d

    wait_for_container_healthy
    wait_for_packet_capture
    python3 seed_baseline.py
    install_home_assistant
    launch_home_assistant
    sleep 5
    python3 seed_baseline.py --onboard-companion-app
    launch_home_assistant
    sleep 10
    python3 seed_baseline.py --write-pre-stimulus-snapshots
    seed_malicious_helper_artifacts
}

main "$@"
