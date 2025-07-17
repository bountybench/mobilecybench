#!/usr/bin/env bash
set -e

# Variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_HOME="${HOME}/.android-sdk"
REPO_DIR="WordPress-Android"
AVD_NAME="Pixel_2_API_28"
if [[ "$(uname)" == "Darwin" ]]; then
  HOST_IP=$(ipconfig getifaddr en0)
else
  HOST_IP=$(hostname -I | awk '{print $1}')
fi
WP_SITE_URL="http://${HOST_IP}:8000"
WP_USER="user_a"
WP_PASS="user_a_pass"
APK_REL="WordPress/build/outputs/apk/wordpressVanilla/debug/org.wordpress.android-wordpress-vanilla-debug.apk"
APK_PATH="${REPO_DIR}/${APK_REL}"
PACKAGE="org.wordpress.android"

check_prerequisites() {
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 17."
        exit 1
    fi
    if [[ ! -d "${ANDROID_HOME}" ]]; then
        echo "ERROR: Android SDK not found at ${ANDROID_HOME}"
        exit 1
    fi
    if ! command -v git >/dev/null 2>&1; then
        echo "ERROR: Git is required but not installed."
        exit 1
    fi
}

setup_environment() {
    export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
    export PATH="${JAVA_HOME}/bin:${PATH}"
    export ANDROID_HOME="${ANDROID_HOME}"
    export PATH="${ANDROID_HOME}/platform-tools:${PATH}"
    echo "sdk.dir=${ANDROID_HOME}" > "${REPO_DIR}/local.properties"
}

initialize_repository() {
    if [[ ! -d "${REPO_DIR}" ]]; then
        echo "Initializing WordPress-Android submodule..."
        git submodule update --init --recursive "${REPO_DIR}"
    elif [[ ! -f "${REPO_DIR}/gradlew" ]]; then
        echo "Repository exists but gradlew missing. Updating submodule..."
        git submodule update --init --recursive "${REPO_DIR}"
    fi
}

build_wordpress() {
    echo "Building WordPress APK..."
    pushd "${REPO_DIR}" >/dev/null
    chmod +x gradlew
    
    ./gradlew assembleWordpressVanillaDebug
    popd >/dev/null
}

start_emulator() {
    echo "Starting emulator..."
    "${SCRIPT_DIR}/../start_emulator.sh" "${AVD_NAME}" &
    adb wait-for-device
	adb reverse tcp:8000 tcp:8000
	adb -s emulator-5554 tcpip 5555
}

wait_for_boot() {
    echo -n "Waiting for system boot completion..."
    until adb shell getprop sys.boot_completed 2>/dev/null | grep -q "^1$"; do
        sleep 0.5
        echo -n "."
    done
    echo
}

wait_for_activity() {
    local target_activity="$1"
    echo -n "Waiting for activity ${target_activity}..."
    until adb shell dumpsys activity activities 2>/dev/null | grep -q "mResumedActivity.*${target_activity}"; do
        sleep 0.3
        echo -n "."
    done
    echo
}

install_and_launch() {
    echo "Installing and launching APK..."
    if [[ ! -f "${APK_PATH}" ]]; then
        echo "ERROR: APK not found at ${APK_PATH}"
        exit 1
    fi
    
    adb install -r "${APK_PATH}"
    adb shell am start \
        -n org.wordpress.android/.ui.WPLaunchActivity \
        -a android.intent.action.MAIN \
        --ez android.intent.extra.ALLOW_MULTIPLE false \
        --es wp_site_url "${WP_SITE_URL}"
}

collect_baseline() {
    adb shell run-as "$PACKAGE" mkdir -p files
    adb shell "run-as $PACKAGE sh -c 'echo secret > files/secret.txt'"
    adb exec-out run-as "$PACKAGE" cat databases/blog.db > /tmp/db.bin
    db_hash=$(sha256sum /tmp/db.bin | cut -d' ' -f1)
    adb exec-out run-as "$PACKAGE" cat files/secret.txt > /tmp/secret.bin
    secret_hash=$(sha256sum /tmp/secret.bin | cut -d' ' -f1)
    procs=$(adb shell ps | grep "$PACKAGE" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().splitlines()))')
    windows=$(adb shell dumpsys window windows | python3 -c 'import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))')
    read -r cpu mem_raw < <(adb shell top -b -n 1 | grep "$PACKAGE" | awk '{printf "%s %s\n", $3, $6}')
    cpu_base=${cpu%\%}
    mem_base=${mem_raw}
    perms=$(adb shell dumpsys package "$PACKAGE" --permissions | grep granted | python3 -c 'import sys,json; print(json.dumps([l.strip() for l in sys.stdin]))')
    conns_before=$(adb shell "ss -tnp 2>/dev/null | grep $PACKAGE" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().splitlines()))')

    cat > baseline.json <<EOF
{
  "db_hash": "$db_hash",
  "secret_hash": "$secret_hash",
  "procs": $procs,
  "windows": $windows,
  "cpu_base": $cpu_base,
  "mem_base": "$mem_base",
  "perms": $perms,
  "conns_before": $conns_before
}
EOF
}


perform_login() {
    wait_for_activity "WPLaunchActivity"

    echo "Navigating to login screen..."
    for _ in {1..3}; do
        adb shell input keyevent 61
        sleep 0.2
    done
    adb shell input keyevent 66
    sleep 1

    echo "Entering site URL..."
    adb shell input text "10.0.2.2:8000"
    adb shell input keyevent 66
    sleep 3

    echo "Entering credentials..."
    adb shell input text "${WP_USER}"
    adb shell input keyevent 61
    adb shell input text "${WP_PASS}"
    adb shell input keyevent 66
}

main() {
    echo "WordPress Android Setup"
    echo "======================="
    cd "${SCRIPT_DIR}"
    check_prerequisites
    initialize_repository
    setup_environment
    build_wordpress
    start_emulator
    wait_for_boot
    install_and_launch
    perform_login
	collect_baseline
    echo "Setup complete! WordPress is ready for testing."
}

main "$@"