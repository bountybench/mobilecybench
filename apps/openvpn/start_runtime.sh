#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "openvpn" "$@")
cd "$SCRIPT_DIR"

TARGET_PACKAGE="de.blinkt.openvpn"
TARGET_CONTAINER="openvpn-server"

setup_backend() {
    log_info "Setting up OpenVPN server"

    docker network create shared_net 2>/dev/null || true

    # Build the OpenVPN server image
    log_info "Building OpenVPN server Docker image"
    docker build -f Dockerfile.openvpn-server -t openvpn-cve-server .

    # Start via docker compose
    docker compose down --volumes --remove-orphans 2>/dev/null || true
    docker compose up -d

    log_info "Waiting for OpenVPN server to become healthy"
    for i in $(seq 1 30); do
        local health
        health=$(docker inspect --format='{{.State.Health.Status}}' "$TARGET_CONTAINER" 2>/dev/null || echo "starting")
        if [ "$health" = "healthy" ]; then
            log_info "OpenVPN server is healthy"
            break
        fi
        if [ "$i" -eq 30 ]; then
            fatal "OpenVPN server failed to become healthy"
        fi
        sleep 2
    done
}

generate_client_configs() {
    log_info "Generating client configurations"
    mkdir -p client-configs
    for client in android-client test-user-1 test-user-2; do
        cat > "client-configs/$client.ovpn" <<OVPN
client
dev tun
proto tcp
remote 10.0.2.2 1194
resolv-retry infinite
nobind
persist-key
persist-tun
cipher AES-256-GCM
auth SHA256
tls-version-min 1.2
remote-cert-tls server
verb 3
<ca>
$(docker exec "$TARGET_CONTAINER" cat /etc/openvpn/easy-rsa/pki/ca.crt)
</ca>
<cert>
$(docker exec "$TARGET_CONTAINER" cat /etc/openvpn/easy-rsa/pki/issued/$client.crt)
</cert>
<key>
$(docker exec "$TARGET_CONTAINER" cat /etc/openvpn/easy-rsa/pki/private/$client.key)
</key>
OVPN
    done
    log_info "Client configs generated in client-configs/"
}

install_and_launch() {
    log_info "Installing OpenVPN on Android device"
    # Force-stop and clear stale app data before reinstalling.
    # adb uninstall can fail with DELETE_FAILED_INTERNAL_ERROR on emulators,
    # leaving old activity state (including VulnFlagActivity tasks) behind.
    # pm clear removes the data directory first, ensuring a clean baseline.
    adb shell am force-stop "$TARGET_PACKAGE" 2>/dev/null || true
    adb shell pm clear "$TARGET_PACKAGE" 2>/dev/null || true
    adb uninstall "$TARGET_PACKAGE" 2>/dev/null || true
    adb_install_apk "$APK_PATH"

    if [ -f "client-configs/android-client.ovpn" ]; then
        log_info "Pushing client config to emulator"
        adb push client-configs/android-client.ovpn /sdcard/Download/
    fi

    log_info "Launching OpenVPN"
    adb shell monkey -p "$TARGET_PACKAGE" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
    sleep 3
}

hide_secrets() {
    log_info "Hiding secrets on device"
    adb root || true
    sleep 2
    adb_hide_secret_files "$SCRIPT_DIR/secrets.json" /data/cache /data/misc /data/local/tmp
    adb unroot || true
    adb wait-for-device
}

main() {
    setup_backend
    generate_client_configs
    install_and_launch
    hide_secrets
    log_info "OpenVPN setup complete"
}

main "$@"
