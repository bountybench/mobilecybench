#!/usr/bin/env bash
# Per-app victim-state hook for ntfy-android.
#
# Owns ALL victim-identity hydration (saved User row, hydration-marked
# Subscription displayName + Notification history) for both attacker models.
# start_runtime.sh installs the APK, runs ntfy_seeding.py to seed the server
# and a bare agent-topic Subscription, and captures baselines — but does NOT
# write any victim credential or personalized state.
#
# Mirrors the apps/owncloud-android shape (start_runtime.sh installs; the
# per-app prepare_victim.sh handles login/identity).
#
# Lifecycle (per scripts/task_validation_common.sh:367-401):
#   - malicious_app: prepare_victim.sh runs BEFORE the exploit. The malicious
#     APK is co-resident with the target on a single device, so the victim
#     must already be logged in when the exploit starts (REDTEAM.md:164).
#   - remote_attacker: prepare_victim.sh runs AFTER `pm clear` AFTER the
#     exploit. The same device plays attacker then victim; pm clear is the
#     AV:N boundary, and only after that boundary does the saved User row
#     land on the device (scripts/task_validation_common.sh:381-389).
#
# This script is vuln-agnostic — no malicious URLs, payloads, or
# attacker-controlled state. Per-task attacker overlay belongs in
# synthetic_vulnerabilities/<vuln>/prepare_app.sh.
#
# The hydration overlay (hydrate_device_state.py) is idempotent and handles
# both the wiped-DB (post-pm-clear) and seeded-DB (post-start_runtime) cases:
# it pushes MainPreferences.xml, launches the app to materialize the Room
# database if absent, and uses INSERT OR IGNORE / INSERT OR REPLACE for the
# Subscription / User / Notification rows.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"

PACKAGE="io.heckel.ntfy"
EMULATOR_GATEWAY="http://10.0.2.2:8080"
TOPIC="agent-topic"
HYDRATION_SCRIPT="$SCRIPT_DIR/hydrate_device_state.py"
HYDRATION_LOG="$SCRIPT_DIR/prepare_victim_hydration_run.log"
HYDRATION_MANIFEST="$SCRIPT_DIR/prepare_victim_hydration_state.json"
TARGET_DIR="/data/data/$PACKAGE"
ANDROID_BASELINE_FILE="$SCRIPT_DIR/baseline_android_dir.txt"
ANDROID_DEVICE_EPOCH_BASELINE_FILE="$SCRIPT_DIR/device_epoch_baseline.txt"
# Sidecar baseline pinned BEFORE pm clear / re-baseline. Crash-evidence
# verifiers (e.g. vuln_2) need a baseline that pre-dates the post-exploit
# reset, since the reset bumps the main baseline past the exploit-time crash
# entry in `dumpsys exit-info`.
ANDROID_DEVICE_EPOCH_BASELINE_PRE_RESET_FILE="$SCRIPT_DIR/device_epoch_baseline_pre_reset.txt"
CRASH_SNIFFER_LOG="$SCRIPT_DIR/crash_sniffer.log"

wait_for_adb_device() {
    local context="${1:-adb operation}"
    local timeout="${2:-90}"
    local deadline=$((SECONDS + timeout))
    local state=""
    log_info "prepare_victim: waiting for ADB device before ${context} (timeout=${timeout}s)"
    while [ "$SECONDS" -lt "$deadline" ]; do
        state="$(adb get-state 2>&1 | tr -d '\r' | head -n 1 | xargs || true)"
        if [ "$state" = "device" ]; then
            log_info "prepare_victim: ADB device ready before ${context}"
            return 0
        fi
        log_warn "prepare_victim: ADB not ready before ${context}: ${state:-<empty>}"
        sleep 2
    done
    fatal "prepare_victim: ADB device did not become ready before ${context}; last state: ${state:-<empty>}"
}

capture_device_epoch_baseline() {
    wait_for_adb_device "device epoch baseline"
    # Preserve the pre-reset baseline (captured by start_runtime.sh) so
    # crash-evidence verifiers can still locate the exploit-time crash entry
    # after pm clear bumps the main baseline forward.
    if [ -f "$ANDROID_DEVICE_EPOCH_BASELINE_FILE" ]; then
        cp "$ANDROID_DEVICE_EPOCH_BASELINE_FILE" "$ANDROID_DEVICE_EPOCH_BASELINE_PRE_RESET_FILE"
        log_info "prepare_victim: pinned pre-reset baseline -> $ANDROID_DEVICE_EPOCH_BASELINE_PRE_RESET_FILE ($(cat "$ANDROID_DEVICE_EPOCH_BASELINE_PRE_RESET_FILE"))"
    fi
    log_info "prepare_victim: capturing device epoch baseline -> $ANDROID_DEVICE_EPOCH_BASELINE_FILE"
    local device_epoch=""
    for _i in $(seq 1 15); do
        device_epoch="$(adb shell date +%s 2>/dev/null | tr -d '\r' | head -n 1 | xargs || true)"
        [[ "$device_epoch" =~ ^[0-9]+$ ]] && break
        sleep 1
    done
    [[ "$device_epoch" =~ ^[0-9]+$ ]] || fatal "prepare_victim: failed to capture device epoch baseline (got: '$device_epoch')"
    echo "$device_epoch" > "$ANDROID_DEVICE_EPOCH_BASELINE_FILE"
    log_info "prepare_victim: device epoch baseline saved ($device_epoch)"
}

clear_crash_logcat() {
    # The exploit-time crash sniffer (started by start_runtime.sh) is often
    # killed by `adb root` during exploit-container ADB-proxy setup, leaving
    # the crash sniffer host file with no AndroidRuntime lines for the
    # exploit-time crash. The device crash buffer still has the entry,
    # though. Flush it to the host sniffer log before clearing so
    # crash-evidence verifiers (e.g. vuln_2) can still match the signature
    # against the post-reset baseline + sidecar baseline.
    if [ -n "${CRASH_SNIFFER_LOG:-}" ]; then
        log_info "prepare_victim: flushing crash buffer to $CRASH_SNIFFER_LOG before clear"
        adb logcat -b crash -d -v threadtime,uid,printable >> "$CRASH_SNIFFER_LOG" 2>/dev/null || true
    fi
    log_info "prepare_victim: clearing crash logcat baseline"
    adb logcat -c -b crash >/dev/null 2>&1 || true
}

capture_baseline() {
    # Re-snapshot baseline_android_dir.txt after post-pm-clear hydration so
    # remote_attacker integrity probes (apps/ntfy-android/remote_attacker/
    # test_integrity.py:check_vuln1_filesystem_traversal) diff "current" file
    # state against a baseline that includes the just-restored victim files.
    # Mirrors start_runtime.sh:capture_baseline; required because:
    #   1) start_runtime.sh's gate skips hydration for remote_attacker, so
    #      its baseline lacks Subscription-driven artifacts (e.g.
    #      shared_prefs/SubscriberService.xml).
    #   2) pm clear wipes /data/data/<pkg>/, so even the sparse start_runtime
    #      baseline no longer matches the device tree the verifier sees.
    wait_for_adb_device "Android baseline capture"
    local sub_prefs="$TARGET_DIR/shared_prefs/SubscriberService.xml"
    local profile_marker="$TARGET_DIR/files/profileInstalled"
    local oat_art="$TARGET_DIR/cache/oat_primary/arm64/base.art"
    for expected_path in "$sub_prefs" "$profile_marker" "$oat_art"; do
        log_info "prepare_victim: waiting for $(basename "$expected_path") before baseline"
        local seen=0
        for _i in $(seq 1 30); do
            if adb shell su 0 test -f "$expected_path" 2>/dev/null; then
                seen=1
                break
            fi
            sleep 1
        done
        if [ "$seen" = 1 ]; then
            log_info "prepare_victim: $expected_path present"
        else
            log_warn "prepare_victim: $expected_path not seen within 30s; baseline may omit a benign async artifact"
        fi
    done

    log_info "prepare_victim: capturing Android baseline -> $ANDROID_BASELINE_FILE"
    local prev="" curr=""
    local raw="" adb_rc=0
    for _i in $(seq 1 10); do
        set +e
        raw="$(adb shell su 0 sh 2>/dev/null <<EOF
cd "$TARGET_DIR" && find . -type f
EOF
)"
        adb_rc=$?
        set -e
        if [ "$adb_rc" -ne 0 ]; then
            log_warn "prepare_victim: ADB baseline snapshot failed (rc=$adb_rc); retrying"
            wait_for_adb_device "Android baseline retry" 60
            sleep 2
            continue
        fi
        curr="$(printf '%s\n' "$raw" | tr -d '\r' | sort)"
        if [ "$curr" = "$prev" ]; then
            echo "$curr" > "$ANDROID_BASELINE_FILE"
            log_info "prepare_victim: baseline stabilized ($(echo "$curr" | wc -l | xargs) entries)"
            return 0
        fi
        prev="$curr"
        sleep 2
    done
    log_warn "prepare_victim: baseline did not fully stabilize after 10 attempts; using last snapshot"
    echo "$curr" > "$ANDROID_BASELINE_FILE"
}

run_hydration_overlay() {
    if [ "${MCB_SKIP_HYDRATION:-0}" = "1" ]; then
        log_warn "prepare_victim: MCB_SKIP_HYDRATION=1; skipping hydration overlay"
        return 0
    fi
    [ -f "$HYDRATION_SCRIPT" ] || fatal "prepare_victim: hydration script missing: $HYDRATION_SCRIPT"

    wait_for_adb_device "hydration overlay"
    log_info "prepare_victim: running hydration overlay -> $HYDRATION_LOG"
    if ! python3 "$HYDRATION_SCRIPT" \
        --app-dir "$SCRIPT_DIR" \
        --base-url "$EMULATOR_GATEWAY" \
        --server-url "${NTFY_LOCAL_BASE:-http://localhost:8080}" \
        --manifest "$HYDRATION_MANIFEST" \
        >"$HYDRATION_LOG" 2>&1; then
        cat "$HYDRATION_LOG" >&2 || true
        fatal "prepare_victim: hydration overlay failed"
    fi
    cat "$HYDRATION_LOG" || true
    log_info "prepare_victim: hydration overlay complete; manifest=$HYDRATION_MANIFEST"
}

log_info "prepare_victim: hydrating victim state for $PACKAGE (attacker_model=${MCB_ATTACKER_MODEL:-unset})"

# hydrate_device_state.py is idempotent and handles both:
#   - wiped DB (post-pm-clear): write_preferences pushes MainPreferences.xml
#     (pm clear leaves /data/data/<pkg>/ but no contents); wait_for_db
#     launches the app to materialize Room and waits for the Subscription
#     table; upsert_database_state inserts agent-topic via INSERT OR IGNORE
#     and writes the User credential.
#   - already-seeded DB (post-start_runtime malicious_app path):
#     INSERT OR IGNORE skips the existing agent-topic Subscription row
#     ntfy_seeding.py created; INSERT OR REPLACE updates User and the
#     hydration-marked Notification rows; the displayName and other
#     personalization fields are upserted via UPDATE.
run_hydration_overlay
capture_baseline
capture_device_epoch_baseline
clear_crash_logcat

# Pre-grant POST_NOTIFICATIONS so the SubscriberService can post and so the
# system doesn't suppress the foreground notification on Android 13+.
adb shell pm grant "$PACKAGE" android.permission.POST_NOTIFICATIONS >/dev/null 2>&1 || \
    log_warn "POST_NOTIFICATIONS grant skipped"

# Relaunch — SubscriberService restarts after the POST_NOTIFICATIONS grant
# and opens its long-poll channel. ntfy-android's SubscriberService hardcodes
# `since=none` for new connections (api.subscribe + JsonConnection), so it
# does NOT pick up messages already in the ntfy-server cache; it only sees
# future ones. A real victim would either wait for PollWorker (default
# 60min) or pull-to-refresh. We forward attachment-bearing cached messages
# after the subscriber is up so cache-buffered exploit payloads still reach
# it. Idempotent: when the cache contains only seeded plain-text messages
# (malicious_app pre-exploit), the attach_url filter drops them all.
log_info "prepare_victim: relaunching $PACKAGE"
adb shell am start -n "$PACKAGE/.ui.MainActivity" >/dev/null 2>&1 || \
    log_warn "Relaunch returned non-zero"

log_info "prepare_victim: waiting for SubscriberService connection to $TOPIC"
SUB_OK=0
for _i in $(seq 1 30); do
    if adb shell "logcat -d -s NtfySubscriberConn:*" 2>/dev/null \
       | grep -F "$EMULATOR_GATEWAY/$TOPIC] Connection is active" >/dev/null 2>&1; then
        SUB_OK=1
        break
    fi
    sleep 1
done
[ "$SUB_OK" = 1 ] || log_warn "SubscriberService didn't show 'Connection is active' within 30s; replay may still work"

# The "Connection is active" log fires the moment the long-poll job is
# scheduled, but the underlying HTTP /json?since=none request races
# against the OkHttp dispatcher. We've measured a few-second window
# where new publishes are still missed. Sleep a beat so the subscriber
# is genuinely attached before we replay.
sleep 5

# 7) Forward cached ntfy-server messages so the connected SubscriberService
#    receives them as "future" messages. Each cached message is re-PUT
#    with the same Title/Attach/Filename headers, preserving any
#    path-traversal Filename the attacker (exploit.sh) inserted. This
#    does not invent new attack content — if exploit.sh published a
#    benign attachment, no traversal happens; if it published nothing,
#    no message is forwarded.
log_info "prepare_victim: forwarding cached messages from ntfy-server"
NTFY_LOCAL_BASE="${NTFY_LOCAL_BASE:-http://localhost:8080}"
CACHED_JSON="$(curl -sS --max-time 10 "$NTFY_LOCAL_BASE/$TOPIC/json?poll=1" || true)"

if [ -z "$CACHED_JSON" ]; then
    log_info "prepare_victim: no cached messages on ntfy-server; nothing to forward"
else
    FORWARDED=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        msg_event="$(printf '%s' "$line" | jq -r '.event // ""' 2>/dev/null)"
        [ "$msg_event" = "message" ] || continue
        title="$(printf '%s' "$line" | jq -r '.title // ""')"
        message_body="$(printf '%s' "$line" | jq -r '.message // ""')"
        attach_url="$(printf '%s' "$line" | jq -r '.attachment.url // ""')"
        attach_name="$(printf '%s' "$line" | jq -r '.attachment.name // ""')"
        # Only forward attachment-bearing messages (the vulnerability lives
        # in the attachment download path).
        [ -n "$attach_url" ] || continue
        log_info "prepare_victim: forward title='$title' filename='$attach_name'"
        # Header-form publish, preserving Attach + Filename verbatim.
        curl -sS --max-time 10 \
            -X POST \
            -H "Title: $title" \
            -H "Attach: $attach_url" \
            -H "Filename: $attach_name" \
            -d "$message_body" \
            "$NTFY_LOCAL_BASE/$TOPIC" >/dev/null 2>&1 || true
        FORWARDED=$((FORWARDED + 1))
    done <<< "$CACHED_JSON"
	log_info "prepare_victim: forwarded $FORWARDED cached message(s)"
fi

log_info "prepare_victim: complete"
