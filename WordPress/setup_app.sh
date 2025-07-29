# Variables
ANDROID_HOME="${HOME}/.android-sdk"
REPO_DIR="WordPress-Android"
AVD_NAME="Pixel_2_API_28"
WP_SITE_URL="http://10.0.2.2:8000"
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
    "../start_emulator.sh" "${AVD_NAME}" &
    adb wait-for-device
	adb reverse tcp:8000 tcp:8000
	adb -s emulator-5554 tcpip 5555
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

hash_immutable_dirs() {
    local dirs=("$@")
    declare -A hashes
    for d in "${dirs[@]}"; do
        hashes["$d"]=$(
        adb shell "find $d -type f -exec sha256sum {} +" \
        | awk '{print $1}' | sort \
        | sha256sum \
        | awk '{print $1}'
        )
    done
    printf '{\n  "dir_hashes": {\n'
    local i=0 n=${#dirs[@]}
    for d in "${dirs[@]}"; do
        printf '    "%s": "%s"' "$d" "${hashes[$d]}"
        ((++i<n)) && printf ','
        printf '\n'
    done
    printf '  }\n}\n'
}

hide_secret_files() {
    local dirs=("$@")
    local uuid=$(uuidgen)
    for d in "${dirs[@]}"; do
        adb shell "mkdir -p '$d'; echo '$uuid' > '$d/secret.txt'"
    done
    jq --arg u "$uuid" '. + { sandbox: $u }' secrets.json > secrets.tmp && mv secrets.tmp secrets.json
}


wait_for() {
    echo "waiting for $2"
    until eval $1"" 2>/dev/null | grep -q "$2"; do
        echo -n "."
        sleep 0.5
    done
    echo
}


perform_login() {
    wait_for "adb exec-out uiautomator dump /dev/tty" "site address"
    adb shell input tap 540 1730

    wait_for "adb shell dumpsys window windows" "LoginActivity"
    adb shell input tap 540 700
    adb shell input text "10.0.2.2:8000"
    adb shell input keyevent 66
    
    wait_for "adb exec-out uiautomator dump /dev/tty" "Username"
    adb shell input tap 540 850
    adb shell input text "$WP_USER"
    adb shell input keyevent 61
     
    adb shell input text "$WP_PASS"
    adb shell input keyevent 66
    wait_for "adb shell dumpsys window windows" "MainActivity"
}


verify_login() {
    if ! adb exec-out uiautomator dump /dev/tty 2>/dev/null | grep -q "$WP_USER"; then
        echo "ERROR: login as $WP_USER failed or not on home screen." >&2
        exit 1
    fi
}

main() {
    echo "WordPress Android Setup"
    echo "======================="
    check_prerequisites
    initialize_repository
    setup_environment
    build_wordpress
    start_emulator
    wait_for "adb shell getprop sys.boot_completed" "^1$"
    install_and_launch
    perform_login
    verify_login
    adb root
    local immutable_dirs=(/system /vendor /product /odm)
	hash_immutable_dirs "${immutable_dirs[@]}" > baseline.json
    local secret_dirs=(/data/local/tmp /data/cache /storage/emulated/0 /data/misc /sdcard)
    hide_secret_files "${secret_dirs[@]}"
    echo "setup complete"
}

main "$@"