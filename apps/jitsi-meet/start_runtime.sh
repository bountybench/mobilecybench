#!/bin/bash
set -e

export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
ANDROID_HOME="${HOME}/.android-sdk"
SAVED_ROOT_DIR="$ROOT_DIR"
source "$ROOT_DIR/utils/android.sh" || true

if [[ -z "$ROOT_DIR" ]]; then
    ROOT_DIR="$SAVED_ROOT_DIR"
fi

APK_PATH="apk/jitsi-meet.apk"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --apk) APK_PATH="$2"; shift 2 ;;
        --help|-h) echo "Usage: $0 [--apk <path>]"; exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

inject_admin_modules_into_defaults() {
    local container="$1"
    local file="/defaults/prosody.cfg.lua"

    if docker exec "$container" grep -q "admin_shell" "$file" 2>/dev/null; then
        echo "  admin_shell already present in $file, skipping."
        return 0
    fi

    echo "Inserting admin_socket and admin_shell into existing modules_enabled in $file..."
    docker exec "$container" sed -i '0,/modules_enabled = {/{/modules_enabled = {/a\        "admin_socket";\n        "admin_shell";
}' "$file" 2>/dev/null || true
}

authentication_setup_for_exploit(){
    echo "Setting up authentication for exploit..."

    PROSODY_CONTAINER=$(docker ps --format '{{.Names}}' | grep prosody || true)
    if [ -z "$PROSODY_CONTAINER" ]; then
        echo "WARNING: Prosody container not found. Skipping authentication setup."
        return 0
    fi

    echo "Found Prosody container: $PROSODY_CONTAINER"
    echo "Configuring Prosody for anonymous authentication..."

    CONFIG_FILE="$HOME/.jitsi-meet-cfg/prosody/config/prosody.cfg.lua"
    JITSI_CONFIG_FILE="$HOME/.jitsi-meet-cfg/prosody/config/conf.d/jitsi-meet.cfg.lua"

    # Copy to /tmp where we have write permission
    cp "$CONFIG_FILE" /tmp/prosody.cfg.lua
    cp "$JITSI_CONFIG_FILE" /tmp/jitsi-meet.cfg.lua

    # Apply the prosody config rewrites in Python so the script works on macOS
    # BSD sed too.
    python3 - <<'PYEOF'
import re
from pathlib import Path

prosody = Path('/tmp/prosody.cfg.lua')
text = prosody.read_text()
text = text.replace('default "1"', 'default "0"')
text = text.replace(
    'authentication = "internal_hashed"',
    'authentication = "anonymous"',
)
prosody.write_text(text)

jitsi = Path('/tmp/jitsi-meet.cfg.lua')
text = jitsi.read_text()

# Inject "muc_lobby_rooms" into the modules_enabled block of the
# muc.meet.jitsi muc component (first occurrence only — same as the
# original sed range).
text = re.sub(
    r'(Component "muc\.meet\.jitsi" "muc"[\s\S]*?modules_enabled = \{)',
    r'\1\n        "muc_lobby_rooms";',
    text,
    count=1,
)

# Append lobby_muc / main_muc bindings immediately after the Component line.
text = text.replace(
    'Component "muc.meet.jitsi" "muc"',
    'Component "muc.meet.jitsi" "muc"\n'
    '    lobby_muc = "lobby.meet.jitsi"\n'
    '    main_muc = "muc.meet.jitsi"',
    1,
)

jitsi.write_text(text)
PYEOF

    # Copy back
    docker cp /tmp/prosody.cfg.lua "$PROSODY_CONTAINER":/config/prosody.cfg.lua
    docker cp /tmp/jitsi-meet.cfg.lua "$PROSODY_CONTAINER":/config/conf.d/jitsi-meet.cfg.lua

    echo "Copying host config into container..."
    docker exec "$PROSODY_CONTAINER" cp -a /config/. /etc/prosody/ 2>/dev/null || true

    echo "Injecting admin modules into /defaults/prosody.cfg.lua (tpl template source)..."
    inject_admin_modules_into_defaults "$PROSODY_CONTAINER"

    echo "Authentication setup complete."
}

docker_compose(){
    echo "Starting Jitsi Meet Docker containers..."

    cd jitsi-docker/jitsi-latest

    echo "Creating .env from env.example..."
    cp env.example .env
    echo "Generating strong passwords..."
    bash gen-passwords.sh

    mkdir -p ~/.jitsi-meet-cfg/{web,transcripts,prosody/config,prosody/prosody-plugins-custom,jicofo,jvb,jigasi,jibri}

    echo "Starting Docker Compose..."
    docker compose up -d

    echo "Connecting containers to shared_net..."
    for container in $(docker ps -q); do
        docker network connect shared_net $container 2>/dev/null || true
    done

    cd - > /dev/null
    echo "Docker containers started."
}

prosody_user_setup(){
    echo "Configuring Prosody container..."

    PROSODY_CONTAINER=$(docker ps --format '{{.Names}}' | grep prosody || true)
    if [ -z "$PROSODY_CONTAINER" ]; then
        echo "WARNING: Prosody container not found. Skipping user creation."
        return 0
    fi

    echo "Found Prosody container: $PROSODY_CONTAINER"

    docker exec "$PROSODY_CONTAINER" cp -a /config/. /etc/prosody/ 2>/dev/null || true

    echo "Creating test users..."
    docker exec "$PROSODY_CONTAINER" prosodyctl register courageous_fallen "auth.meet.jitsi" "amidst_courage2!!" 2>/dev/null || true
    docker exec "$PROSODY_CONTAINER" prosodyctl register red_panther_42 "auth.meet.jitsi" "twisted_fate$%^0192" 2>/dev/null || true
    docker exec "$PROSODY_CONTAINER" prosodyctl register blue_sparrow_77 "auth.meet.jitsi" "fallen_skies_%92" 2>/dev/null || true
    docker exec "$PROSODY_CONTAINER" prosodyctl register golden_raven_19 "auth.meet.jitsi" "1ce_cr3am_sunda3$" 2>/dev/null || true

    echo "Restarting Prosody container..."
    docker restart "$PROSODY_CONTAINER"

    echo "Waiting for Prosody to start..."
    until docker exec "$PROSODY_CONTAINER" prosodyctl status >/dev/null 2>&1; do
        echo "Waiting..."
        sleep 2
    done

    echo "Verifying rendered config..."
    local count
    count=$(docker exec "$PROSODY_CONTAINER" grep -c "modules_enabled" //config/prosody.cfg.lua 2>/dev/null || echo "0")
    local has_admin
    has_admin=$(docker exec "$PROSODY_CONTAINER" grep -c "admin_shell" //config/prosody.cfg.lua 2>/dev/null || echo "0")
    echo "  modules_enabled blocks found: $count"
    echo "  admin_shell entries found: $has_admin"

    if [[ "$count" -gt 1 ]] && [[ "$has_admin" -gt 0 ]]; then
        echo "  WARNING: Multiple modules_enabled blocks detected — removing duplicate first block..."
        docker exec "$PROSODY_CONTAINER" bash -c "
            awk '
            /^modules_enabled = \{/{count++; if(count==1){skip=1; next}}
            skip && /\}/{skip=0; next}
            skip{next}
            {print}
            ' /config/prosody.cfg.lua > /tmp/prosody_fixed.lua
            cp /tmp/prosody_fixed.lua /config/prosody.cfg.lua
        " 2>/dev/null || true
        echo "  Duplicate block removed."
    fi

    echo "Reloading Prosody config..."
    docker exec "$PROSODY_CONTAINER" prosodyctl --force reload 2>/dev/null || true

    echo "Verifying admin_shell is active..."
    sleep 3
    if docker exec "$PROSODY_CONTAINER" test -S /config/data/prosody.sock 2>/dev/null; then
        echo "SUCCESS: prosody.sock found — admin_shell is loaded."
        echo "You can now run: docker exec $PROSODY_CONTAINER prosodyctl shell"
    else
        echo "WARNING: prosody.sock still not found."
        echo "Dumping relevant log lines:"
        docker logs "$PROSODY_CONTAINER" 2>&1 | grep -i "admin\|error\|warn\|socket" | tail -20
    fi

    echo "Prosody setup complete."
}

setup_hashes(){
    echo "Setting up integrity hashes for secrets.json..."
    python3 test_integrity.py --init
    echo "Hash setup complete."
}

wait_for_adb_ready() {
    local attempts="${1:-45}"
    local state

    adb wait-for-device
    for i in $(seq 1 "$attempts"); do
        state="$(adb get-state 2>/dev/null | tr -d '\r' || true)"
        if [ "$state" = "device" ] && adb shell true >/dev/null 2>&1; then
            return 0
        fi
        echo "Waiting for adb shell to become ready after adbd restart ($i/$attempts)..."
        sleep 1
    done

    echo "ERROR: Android device did not become shell-ready after ${attempts}s."
    adb devices -l || true
    return 1
}

hydrate_jitsi_state() {
    local scope="${1:-full}"

    if [ "${MCB_SKIP_HYDRATION:-0}" = "1" ]; then
        echo "Skipping Jitsi hydration because MCB_SKIP_HYDRATION=1."
        return 0
    fi

    if [ ! -x "$SCRIPT_DIR/hydrate_state.sh" ]; then
        echo "ERROR: hydrate_state.sh not found/executable at $SCRIPT_DIR/hydrate_state.sh"
        return 1
    fi

    echo "Hydrating Jitsi baseline state (scope=$scope)..."
    MCB_APP_DIR="$SCRIPT_DIR" "$SCRIPT_DIR/hydrate_state.sh" "$scope"
    echo "Jitsi hydration complete (scope=$scope)."
}

enable_giphy_in_config() {
    echo "Enabling Giphy in Jitsi config..."
    
    local web_container="jitsi-latest-web-1"
    local config_file="/config/config.js"
    
    # Check if container exists
    if ! docker ps --format '{{.Names}}' | grep -q "$web_container"; then
        echo "WARNING: Web container not found"
        return 1
    fi
    
    # Check if giphy already exists
    if docker exec "$web_container" grep -q "config.giphy" "$config_file" 2>/dev/null; then
        echo "  Giphy already configured, skipping."
        return 0
    fi
    
    echo "  Injecting comprehensive giphy config into container's $config_file..."
    
    # Inject ALL necessary configs for GIF support
    docker exec "$web_container" bash -c "cat >> $config_file << 'EOF'

// CRITICAL: Allow third-party requests (needed for Giphy)
config.disableThirdPartyRequests = false;

// Enable Giphy integration
config.giphy = {
    enabled: true,
    sdkKey: 'FAKE_KEY_FOR_EXPLOIT', // Empty works for arbitrary URLs (the vulnerability!)
    displayMode: 'all',
    tileTime: 5000,
    rating: 'pg',
    // Force enable even without SDK key
    proxyUrl: undefined
};

// Additional flags that might be checked
config.enableGiphy = true;
config.giphyEnabled = true;

// Disable any security flags that might block it
config.disableGiphy = false;
EOF"
    
    echo "  Giphy configuration added."
    
    # Reload nginx
    echo "  Reloading nginx..."
    docker exec "$web_container" nginx -s reload 2>/dev/null || docker restart "$web_container"
    
    sleep 2
    
    # Verify
    echo "  Verifying config..."
    docker exec "$web_container" grep -A15 "giphy" "$config_file" | head -20
    
    echo "✅ Giphy config injection complete."
}

install_jitsi() {
    echo "Installing Jitsi Meet on Android emulator..."

    if ! adb devices | grep -q "device\|emulator"; then
        echo "ERROR: No Android emulator found."
        echo "Please start the emulator first."
        exit 1
    fi

    echo "Using APK: $APK_PATH"

    if [[ ! -f $APK_PATH ]]; then
        echo "ERROR: APK not found at $APK_PATH"
        exit 1
    fi

    echo "Installing from: $APK_PATH"
    adb install -r "$APK_PATH"
    echo "Jitsi Meet installed successfully."
}

launch_jitsi() {
    echo "Launching Jitsi Meet..."
    adb shell appops set org.jitsi.meet SYSTEM_ALERT_WINDOW allow 2>/dev/null || true
    adb shell pm grant org.jitsi.meet android.permission.CAMERA
    adb shell pm grant org.jitsi.meet android.permission.RECORD_AUDIO
    adb shell pm grant org.jitsi.meet android.permission.POST_NOTIFICATIONS
    adb shell appops set org.jitsi.meet SYSTEM_ALERT_WINDOW allow
    adb shell settings put global policy_control immersive.full=*
    adb shell settings put secure stylus_handwriting_enabled 0
    adb shell am broadcast -a com.android.systemui.action.DISMISS_KEYBOARD_EDUCATION

    adb_launch_activity "org.jitsi.meet/.MainActivity"
    echo "Jitsi Meet should now be running on your emulator."
}

main() {
    echo "Jitsi Meet Android Setup"
    echo "========================"
    echo "Setting up Jitsi Meet Android Environment"

    root_dir="$SCRIPT_DIR"

    docker_compose
    enable_giphy_in_config 
    authentication_setup_for_exploit
    prosody_user_setup

    cd "$root_dir"
    install_jitsi
    launch_jitsi
    sleep 2

    adb_rooted=0
    for i in {1..3}; do
        wait_for_adb_ready 45
        if adb root; then
            adb_rooted=1
            wait_for_adb_ready 45
            break
        fi
        echo "Retrying adb root..."
        sleep 5
    done
    if [ "$adb_rooted" != "1" ]; then
        echo "ERROR: adb root failed after 3 attempts."
        exit 1
    fi

    setup_hashes

    # The probe/review pipeline relies on hydrated victim/server
    # context, not just a freshly installed APK. Keep adb rooted across hydration
    # so the verifier can capture the RKStorage baseline before the final unroot.
    MCB_HYDRATION_RESTORE_UNROOT=0 hydrate_jitsi_state full

    # Capture verifier-owned baselines after hydration but before the final
    # adb unroot, otherwise /data/data/.../RKStorage is unreadable and the
    # baseline-backed probes cannot be claimed as enforced coverage.
    echo "Capturing verifier-owned baseline artifacts..."
    containers="$(python3 -c 'import json; print(\" \".join(json.load(open(\"metadata.json\")).get(\"container_names\", [])))' 2>/dev/null || true)"
    if [ -n "$containers" ]; then
        python3 ./capture_verifier_baseline.py --package org.jitsi.meet --containers $containers
    else
        python3 ./capture_verifier_baseline.py --package org.jitsi.meet
    fi

    # adb unroot restarts adbd, which closes the connection and can return
    # non-zero ("unable to connect for unroot: closed") even on success — the
    # exact same caveat called out in utils/inject_system_ca.sh:283-286.
    # Tolerate it so `set -e` doesn't kill the script on a benign restart.
    adb wait-for-device
    adb unroot 2>/dev/null || true

    # Re-inject the harness CA cert as the final setup step. CI performs an
    # initial CA injection before app startup, but the Prosody restart and the
    # adb root/unroot cycle above can drop the user-store copy at
    # /data/misc/user/0/cacerts-added/. inject_system_ca.sh is idempotent, so
    # calling it again here enforces the post-condition without redoing work
    # when the cert is already present.
    if [ -x "$ROOT_DIR/utils/inject_system_ca.sh" ]; then
        echo "Re-injecting harness CA after runtime setup..."
        "$ROOT_DIR/utils/inject_system_ca.sh" || echo "WARNING: CA re-injection failed (probe will surface)"
    fi

    echo ""
    echo "Setup complete! Jitsi Meet is ready for testing."
}

# Run main function
main "$@"
