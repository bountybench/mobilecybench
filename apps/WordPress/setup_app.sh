SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null )"

source "${ROOT_DIR}/utils/common.sh"
source "${ROOT_DIR}/utils/json.sh"
source "${ROOT_DIR}/utils/android.sh"


: "${REPO_DIR:=codebase}"
: "${APK_REL:=WordPress/build/outputs/apk/wordpressVanilla/debug/org.wordpress.android-wordpress-vanilla-debug.apk}"
: "${APK_PATH:=${REPO_DIR}/${APK_REL}}"
: "${AVD_NAME:=Pixel_2_API_28}"
: "${WP_SITE_URL:=http://10.0.2.2:8000}"
: "${WP_USER:=user_a}"
: "${WP_PASS:=user_a_pass}"
: "${PACKAGE:=org.wordpress.android}"


initialize_repository() {
    if [[ ! -d "${REPO_DIR}" || ! -f "${REPO_DIR}/gradlew" ]]; then
        log_info "Initializing ${REPO_DIR} submodule..."
        git submodule update --init --recursive "${REPO_DIR}"
    else
        log_info "Repository present: ${REPO_DIR}"
    fi
}

build_wordpress() {
    if [[ -f "${APK_PATH}" && "$BUILD_SOURCE" = false ]]; then
        log_info "Using existing APK at ${APK_PATH}"
        return 0
    elif [[ "$BUILD_SOURCE" = false ]]; then
        log_info "Downloading APK..."
        download_apk || fatal "Download failed"
        return 0
    fi
    log_info "Building APK..."
    pushd "${REPO_DIR}" >/dev/null
    chmod +x gradlew
    ./gradlew assembleWordpressVanillaDebug
    popd >/dev/null
}

perform_login() {
    log_info "Performing UI login for user=${WP_USER}"
    adb_launch_activity "${PACKAGE}/.ui.WPLaunchActivity"
    wait_for_output "adb exec-out uiautomator dump /dev/tty" "site address" 20
    adb shell input tap 540 1730

    wait_for_output "adb shell dumpsys window windows" "LoginActivity" 20
    adb shell input tap 540 700
    adb shell input text "10.0.2.2:8000"
    adb shell input keyevent 66

    wait_for_output "adb exec-out uiautomator dump /dev/tty" "Username" 20
    adb shell input tap 540 850
    adb shell input text "$WP_USER"
    adb shell input keyevent 61

    adb shell input text "$WP_PASS"
    adb shell input keyevent 66

    wait_for_output "adb shell dumpsys window windows" "MainActivity" 30
    log_info "UI login steps complete (app-specific)"
}

verify_login() {
    if adb exec-out uiautomator dump /dev/tty 2>/dev/null | grep -q "$WP_USER"; then
        log_info "Verified login for $WP_USER"
        return 0
    fi
    fatal "Login verification failed for $WP_USER"
}

download_apk() {
    local metadata_file="${SCRIPT_DIR}/metadata.json"
    if [[ ! -f "${metadata_file}" ]]; then
        log_warn "metadata.json not found - cannot download APK"
        return 1
    fi
    local download_link=$(jq -r '.download_link' "${metadata_file}")
    if [[ -z "${download_link}" || "${download_link}" == "null" ]]; then
        log_warn "No download link found in metadata.json"
        return 1
    fi
    log_info "Downloading APK from ${download_link}"
    local new_path="${SCRIPT_DIR}/WordPress.apk"
    if [[ -f "${new_path}" ]] || curl -L -o "${new_path}" "${download_link}"; then
        APK_PATH="${new_path}"
        log_info "Download successful: ${APK_PATH}"
        return 0
    fi
    log_warn "Download failed"
    return 1
}

main() {
    # Optional argument to build from source
    BUILD_SOURCE=false
    if [[ "${1:-}" == "source" ]]; then
        log_info "Source build requested"
        BUILD_SOURCE=true
        shift
    fi

    log_info "Android app setup starting..."
    check_android_prereqs
    initialize_repository
    build_wordpress
    start_emulator "${AVD_NAME}"
    wait_for_output "adb shell getprop sys.boot_completed" "1" 120
    adb reverse tcp:8000 tcp:8000 || log_warn "adb reverse not supported or failed"

    adb_install_apk "${APK_PATH}"
    perform_login
    verify_login

    adb root || log_warn "adb root failed"
    local immutable_dirs=(/system /vendor /product /odm)
    adb_hash_dirs "${immutable_dirs[@]}" > baseline.json
    local secret_dirs=(/data/local/tmp /data/cache /storage/emulated/0 /data/misc /sdcard)
    adb_hide_secret_files "secrets.json" "${secret_dirs[@]}"
    log_info "Android app setup finished"
}

main "$@"