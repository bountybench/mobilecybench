#!/usr/bin/env bash

OWNTRACKS_EVIDENCE_DIR="${MCB_OWNTRACKS_EVIDENCE_DIR:-${TMPDIR:-/tmp}/mobilecybench-owntracks-evidence}"
OWNTRACKS_STAGE_LOG="$OWNTRACKS_EVIDENCE_DIR/stages.log"

ensure_owntracks_evidence_dir() {
    mkdir -p "$OWNTRACKS_EVIDENCE_DIR"
}

log_owntracks_stage() {
    local stage="$1"
    ensure_owntracks_evidence_dir
    printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$stage" | tee -a "$OWNTRACKS_STAGE_LOG" >&2
}

current_foreground_activity() {
    local raw
    raw="$(adb shell dumpsys activity activities 2>/dev/null || true)"
    RAW_ACTIVITY_DUMP="$raw" python3 - <<'PY'
import re
import os

text = os.environ.get("RAW_ACTIVITY_DUMP", "").replace("\r", "")
patterns = [
    r"mResumedActivity:.*? ([A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+)",
    r"topResumedActivity=.*? ([A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+)",
    r"ResumedActivity:.*? ([A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+)",
]
for pattern in patterns:
    match = re.search(pattern, text)
    if match:
        print(match.group(1))
        raise SystemExit(0)
raise SystemExit(1)
PY
}

read_device_pref_string() {
    local package_name="$1"
    local pref_key="$2"
    local raw
    raw="$(adb shell su 0 sh -lc "cat '/data/data/$package_name/shared_prefs/${package_name}_preferences.xml'" 2>/dev/null || true)"
    RAW_PREF_XML="$raw" python3 - "$pref_key" <<'PY'
import os
import sys
import xml.etree.ElementTree as ET

key = sys.argv[1]
raw = os.environ.get("RAW_PREF_XML", "").replace("\r", "")
root = ET.fromstring(raw)
for child in root:
    if child.attrib.get("name") != key:
        continue
    if child.tag == "string":
        print(child.text or "")
    else:
        print(child.attrib.get("value", child.text or ""))
    raise SystemExit(0)
raise SystemExit(1)
PY
}

assert_device_path_absent() {
    local path="$1"
    local message="$2"
    if adb shell su 0 test -e "$path" >/dev/null 2>&1; then
        fail_with_owntracks_evidence "$message"
    fi
}

assert_device_path_present() {
    local path="$1"
    local message="$2"
    if ! adb shell su 0 test -e "$path" >/dev/null 2>&1; then
        fail_with_owntracks_evidence "$message"
    fi
}

capture_owntracks_evidence() {
    local label="$1"
    local slug
    slug="$(printf '%s' "$label" | tr ' /:' '___')"
    local target_dir="$OWNTRACKS_EVIDENCE_DIR/$slug"
    local ui_device_path="/sdcard/${slug}_ui.xml"

    ensure_owntracks_evidence_dir
    mkdir -p "$target_dir"

    adb wait-for-device >/dev/null 2>&1 || true
    current_foreground_activity > "$target_dir/foreground_activity.txt" 2>/dev/null || true
    adb shell dumpsys activity activities > "$target_dir/dumpsys_activity.txt" 2>/dev/null || true
    adb shell dumpsys window windows > "$target_dir/dumpsys_windows.txt" 2>/dev/null || true
    adb shell uiautomator dump "$ui_device_path" >/dev/null 2>&1 || true
    adb pull "$ui_device_path" "$target_dir/ui.xml" >/dev/null 2>&1 || true
    adb exec-out screencap -p > "$target_dir/screen.png" 2>/dev/null || true
    adb logcat -d > "$target_dir/logcat.txt" 2>/dev/null || true

    if [[ -n "${PKG:-}" ]]; then
        adb shell dumpsys package "$PKG" > "$target_dir/dumpsys_package.txt" 2>/dev/null || true
        adb shell su 0 sh -lc "cat '/data/data/$PKG/shared_prefs/${PKG}_preferences.xml'" > "$target_dir/preferences.xml" 2>/dev/null || true
        adb shell su 0 sh -lc "find '/data/data/$PKG/files/mobilecybench' -maxdepth 2 -type f -o -type d" > "$target_dir/mobilecybench_tree.txt" 2>/dev/null || true
    fi

    if command -v docker >/dev/null 2>&1; then
        docker ps --format '{{.Names}} {{.Status}}' > "$target_dir/docker_ps.txt" 2>/dev/null || true
        docker inspect mosquitto > "$target_dir/docker_inspect_mosquitto.json" 2>/dev/null || true
        docker logs mosquitto > "$target_dir/docker_logs_mosquitto.txt" 2>&1 || true
        if [[ -n "${MONITOR_LOG_IN_CONTAINER:-}" ]]; then
            docker exec mosquitto sh -lc "cat '$MONITOR_LOG_IN_CONTAINER' 2>/dev/null || true" > "$target_dir/monitor_log.txt" 2>/dev/null || true
        fi
    fi
}

fail_with_owntracks_evidence() {
    local message="$1"
    trap - ERR
    log_owntracks_stage "failure: $message"
    capture_owntracks_evidence "failure"
    fatal "$message"
}

assert_map_ready_state() {
    local expected_package="$1"
    local current_activity=""
    current_activity="$(current_foreground_activity 2>/dev/null || true)"
    if [[ "$current_activity" != "$expected_package/.ui.map.MapActivity" ]]; then
        fail_with_owntracks_evidence "expected foreground activity $expected_package/.ui.map.MapActivity, got ${current_activity:-<none>}"
    fi

    local ui_file="$OWNTRACKS_EVIDENCE_DIR/ready_state_ui.xml"
    adb shell uiautomator dump /sdcard/ready_state_ui.xml >/dev/null 2>&1 || fail_with_owntracks_evidence "uiautomator dump failed during ready-state verification"
    adb pull /sdcard/ready_state_ui.xml "$ui_file" >/dev/null 2>&1 || fail_with_owntracks_evidence "failed to pull ready-state UI dump"

    if ! grep -F -q "${expected_package}:id/fabMyLocation" "$ui_file"; then
        fail_with_owntracks_evidence "ready-state UI dump missing fabMyLocation oracle"
    fi
}
