#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/utils.sh"

: "${AVD_NAME:=Pixel_2_API_28}"
: "${WP_SITE_URL:=http://127.0.0.1}"
: "${WP_USER:=user_a}"
: "${WP_PASS:=user_a_pass}"
: "${PACKAGE:=org.wordpress.android}"

perform_login() {
    log_info "Performing UI login for user=${WP_USER}"
    adb_launch_activity "${PACKAGE}/.ui.WPLaunchActivity"
    wait_for_output "adb shell dumpsys activity activities" "Resumed: ActivityRecord.*org.wordpress.android" 60
    wait_for_output "adb exec-out uiautomator dump /dev/tty || (adb shell uiautomator dump /sdcard/window_dump.xml >/dev/null && adb shell cat /sdcard/window_dump.xml)" "WordPress.com" 60
    adb shell input tap 540 1700

    wait_for_output "adb shell dumpsys window windows" "LoginActivity" 60
    adb shell input tap 540 700
    adb shell input text "127.0.0.1"
    adb shell input keyevent 66

    wait_for_output "adb exec-out uiautomator dump /dev/tty" "Username" 60
    adb shell input tap 540 850
    adb shell input text "$WP_USER"
    adb shell input keyevent 61

    adb shell input text "$WP_PASS"
    adb shell input keyevent 66

    wait_for_output "adb exec-out uiautomator dump /dev/tty" "Choose a site to open" 60
    log_info "UI login steps complete (app-specific)"
}

verify_login() {
    local ui_dump=$(adb exec-out uiautomator dump /dev/tty 2>/dev/null)
    if echo $ui_dump | grep -q "$WP_USER"; then
        log_info "Verified login for $WP_USER"
        return 0
    fi
    fatal "Login verification failed for $WP_USER"
}

main() {
    APK_PATH=${1:-codebase/WordPress/build/outputs/apk/wordpressVanilla/debug/org.wordpress.android-wordpress-vanilla-debug.apk}
    log_info "Android app setup starting..."
    start_emulator "${AVD_NAME}"
    adb shell settings put global window_animation_scale 0
    adb shell settings put global transition_animation_scale 0
    adb shell settings put global animator_duration_scale 0
    adb reverse tcp:80 tcp:80 || log_warn "adb reverse not supported or failed"

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