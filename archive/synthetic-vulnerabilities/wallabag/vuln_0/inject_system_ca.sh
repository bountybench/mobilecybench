#!/usr/bin/env bash
set -euo pipefail

# inject_system_ca.sh — Add a CA cert to the Android emulator trust stores
# so apps and Chrome trust local HTTPS backends (e.g. 10.0.2.2).
#
# Two trust stores are populated:
#
# 1. System store (/system/etc/security/cacerts/) — trusted by all apps via
#    Android's default TrustManager. Injected via tmpfs overlay (API <= 33)
#    or tmpfs + nsenter bind-mount into zygote namespaces (API >= 34).
#
# 2. User store (/data/misc/user/0/cacerts-added/) — trusted by Chrome without
#    Certificate Transparency (CT) enforcement. Chrome 121+ on Android uses the
#    Chrome Root Store and treats system-injected CAs as "public" CAs requiring
#    SCTs. User-installed CAs are exempt from CT as they represent intentional
#    local trust decisions. This matters for apps using OAuth/Chrome Custom Tabs.
#
# Both stores are non-persistent — lost on emulator reboot.
#
# API-level handling for system store:
#   API <= 33: tmpfs overlay; apps read from /system/etc/security/cacerts.
#   API >= 34: Android 14+ moved CAs to /apex/com.android.conscrypt/cacerts with
#     per-process mount namespaces. We use nsenter to bind-mount the overlay.
#     https://httptoolkit.com/blog/android-14-install-system-ca-certificate/
#
# Idempotent: skips injection if the cert is already present and visible.
#
# Prerequisites: the emulator must be fully booted before running this script.
# All callers (CI, local CI, Python orchestrator) handle boot-wait upstream.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=utils/common.sh
source "$SCRIPT_DIR/common.sh"

get_zygote_pid_snapshot() {
  adb shell "pidof zygote64 zygote 2>/dev/null || true" |
    tr -d '\r' |
    tr ' ' '\n' |
    awk 'NF' |
    sort -n -u
}

wait_for_stable_zygote_pids() {
  local previous="" current="" attempt

  for attempt in 1 2 3 4 5; do
    current="$(get_zygote_pid_snapshot | paste -sd' ' -)"
    if [[ -n "$current" && "$current" == "$previous" ]]; then
      printf '%s\n' "$current"
      return 0
    fi
    previous="$current"
    sleep 2
  done

  return 1
}

collect_mount_namespace_targets() {
  local zygotes="${1:-}"

  {
    printf '%s\n' "$zygotes" | tr ' ' '\n'
    if [[ -n "$zygotes" ]]; then
      adb shell "ps -A -o PID,PPID | awk -v z=\"$zygotes\" 'BEGIN{split(z,a,\" \"); for (i in a) parents[a[i]]=1} \$2 in parents {print \$1}'"
    fi
  } |
    tr -d '\r' |
    awk 'NF && !seen[$0]++'
}

log_namespace_target_diagnostics() {
  local pid="$1"
  local details=""

  set +e
  details="$(
    adb shell "su 0 sh -c 'ps -A -o PID,PPID,NAME | awk \"\\\$1==$pid { print }\"; printf \"mount-ns: \"; if [ -e /proc/$pid/ns/mnt ]; then readlink /proc/$pid/ns/mnt; else echo missing; fi'" 2>&1 |
      tr -d '\r'
  )"
  set -e

  [[ -n "$details" ]] && printf '%s\n' "$details" >&2
}

check_cert_visibility_in_namespaces() {
  local cert_basename="$1"
  local mode="${2:-strict}"
  local zygotes="" pid="" rc=0 seen_any=0 all_visible=0 verify_attempt=0 max_attempts=1 visibility_output=""

  [[ "$mode" == "strict" ]] && max_attempts=5

  for ((verify_attempt = 1; verify_attempt <= max_attempts; verify_attempt++)); do
    seen_any=0
    all_visible=1

    if ! zygotes="$(wait_for_stable_zygote_pids)"; then
      if [[ "$mode" == "quiet" ]]; then
        return 1
      fi
      if [[ "$verify_attempt" -lt "$max_attempts" ]]; then
        log_warn "Could not observe stable zygote PIDs for verification (attempt $verify_attempt/$max_attempts)"
        sleep 2
        continue
      fi
      log_error "Could not observe stable zygote PIDs for namespace verification"
      return 1
    fi

    while IFS= read -r pid; do
      [[ -n "$pid" ]] || continue
      seen_any=1

      set +e
      visibility_output="$(adb shell "su 0 sh -c '[ -e /proc/$pid/ns/mnt ] || exit 3; nsenter --mount=/proc/$pid/ns/mnt -- ls /apex/com.android.conscrypt/cacerts/$cert_basename'" 2>&1)"
      rc=$?
      set -e

      case "$rc" in
        0)
          ;;
        3)
          if [[ "$mode" == "quiet" ]]; then
            return 1
          fi
          all_visible=0
          log_warn "Namespace target PID $pid disappeared during verification (attempt $verify_attempt/$max_attempts)"
          break
          ;;
        *)
          if [[ "$mode" == "quiet" ]]; then
            return 1
          fi
          all_visible=0
          if [[ "$verify_attempt" -lt "$max_attempts" ]]; then
            log_warn "Cert not yet visible in namespace target PID $pid (attempt $verify_attempt/$max_attempts)"
            break
          fi
          log_error "Cert not visible in namespace target PID $pid"
          [[ -n "$visibility_output" ]] && printf '%s\n' "$visibility_output" >&2
          log_namespace_target_diagnostics "$pid"
          return 1
          ;;
      esac
    done < <(collect_mount_namespace_targets "$zygotes")

    if [[ "$seen_any" -eq 0 ]]; then
      if [[ "$mode" == "quiet" ]]; then
        return 1
      fi
      all_visible=0
      if [[ "$verify_attempt" -lt "$max_attempts" ]]; then
        log_warn "No zygote namespaces found for verification (attempt $verify_attempt/$max_attempts)"
        sleep 2
        continue
      fi
      log_error "No zygote namespaces found for verification"
      return 1
    fi

    [[ "$all_visible" -eq 1 ]] && return 0
    [[ "$verify_attempt" -lt "$max_attempts" ]] && sleep 2
  done

  return 1
}

inject_tmpfs_overlay() {
  # API <= 33: tmpfs overlay on the system cert store.
  # 1. Copy existing certs to a temp dir
  # 2. Mount tmpfs over /system/etc/security/cacerts (hides original, stays read-only)
  # 3. Copy back original certs + our custom cert
  log_info "Using API <= 33 method (tmpfs overlay)"
  adb shell 'su 0 sh -s' <<EOF
set -e
CERT="/data/local/tmp/$CERT_BASENAME"
STORE=/system/etc/security/cacerts

if ! mountpoint -q "\$STORE"; then
  TMP=/data/local/tmp/cacerts-copy
  rm -rf "\$TMP"
  mkdir -p "\$TMP"
  cp \$STORE/* "\$TMP"/
  mount -t tmpfs tmpfs "\$STORE"
  cp "\$TMP"/* "\$STORE"/
  rm -rf "\$TMP"
fi

cp "\$CERT" "\$STORE/"
chown root:root "\$STORE"/*
chmod 644 "\$STORE"/*
chcon u:object_r:system_file:s0 "\$STORE"/*
EOF
}

inject_tmpfs_overlay_with_nsenter() {
  # API >= 34 (Android 14+): certs moved to /apex/com.android.conscrypt/cacerts
  # with per-process mount namespaces. tmpfs overlay alone isn't visible to apps.
  #
  # Two phases:
  #   1. Set up tmpfs overlay containing stock certs + our CA (simple, always works)
  #   2. Bind-mount overlay into each zygote/app mount namespace, then verify
  #      cert is actually visible. Retry until verification passes — this is
  #      robust against zygote restarts and PID instability after boot.
  log_info "Using API >= 34 method (tmpfs overlay + nsenter bind-mount)"

  # Phase 1: Populate /system/etc/security/cacerts via tmpfs overlay.
  adb shell 'su 0 sh -s' <<EOF
set -e
CERT="/data/local/tmp/$CERT_BASENAME"
STORE=/system/etc/security/cacerts
APEX=/apex/com.android.conscrypt/cacerts
TMP=/data/local/tmp/cacerts-copy

rm -rf "\$TMP"
mkdir -p -m 700 "\$TMP"
cp \$APEX/* "\$TMP"/

mountpoint -q "\$STORE" || mount -t tmpfs tmpfs "\$STORE"
rm -f "\$STORE"/*
cp "\$TMP"/* "\$STORE"/
cp "\$CERT" "\$STORE"/

chown root:root "\$STORE"/*
chmod 644 "\$STORE"/*
chcon u:object_r:system_file:s0 "\$STORE"/*

rm -rf "\$TMP"
EOF

  # Phase 2: Bind-mount into per-process namespaces until verified.
  # Uses host-side functions (wait_for_stable_zygote_pids, collect_mount_namespace_targets,
  # check_cert_visibility_in_namespaces) — no duplicated device-side logic.
  local max_attempts=5 attempt zygotes pid

  for ((attempt = 1; attempt <= max_attempts; attempt++)); do
    # Already visible (prior run or previous attempt succeeded)?
    if check_cert_visibility_in_namespaces "$CERT_BASENAME" quiet; then
      return 0
    fi

    if ! zygotes="$(wait_for_stable_zygote_pids)"; then
      log_warn "Zygote PIDs not stable yet (attempt $attempt/$max_attempts)"
      sleep 3
      continue
    fi

    # Bind-mount into each zygote + child namespace. Failures are non-fatal —
    # verification below determines success. PIDs can vanish between collection
    # and bind-mount; the || true handles that gracefully.
    while IFS= read -r pid; do
      [[ -n "$pid" ]] || continue
      adb shell "su 0 sh -c '[ -e /proc/$pid/ns/mnt ] && nsenter --mount=/proc/$pid/ns/mnt -- /bin/mount --bind /system/etc/security/cacerts /apex/com.android.conscrypt/cacerts'" 2>/dev/null || true
    done < <(collect_mount_namespace_targets "$zygotes")

    # Check if cert is now visible in all namespaces
    if check_cert_visibility_in_namespaces "$CERT_BASENAME" quiet; then
      return 0
    fi

    log_warn "Cert not yet visible in all namespaces (attempt $attempt/$max_attempts)"
    [[ "$attempt" -lt "$max_attempts" ]] && sleep 3
  done

  # Final attempt with full diagnostics
  check_cert_visibility_in_namespaces "$CERT_BASENAME"
}

# Find cert: use arg if provided, otherwise auto-discover from tls/
CERT_PATH="${1:-$(ls "$REPO_ROOT"/tls/*.0 2>/dev/null | head -1 || true)}"
[[ -n "$CERT_PATH" && -f "$CERT_PATH" ]] || fatal "No cert found. Place <hash>.0 in tls/"
CERT_BASENAME="$(basename "$CERT_PATH")"

# Ensure adb root access for cert injection.
# adb root restarts adbd, which closes the connection and returns non-zero
# even on success ("unable to connect for root: closed"). Ignore the exit code.
adb root 2>/dev/null || true
adb wait-for-device >/dev/null

# Always drop root on exit (including early returns and errors).
# adb unroot restarts adbd, which closes the connection and returns non-zero
# even on success ("unable to connect for unroot: closed"). Ignore the exit
# code and instead verify the resulting state via stdout: if adbd is still
# uid=0 after the wait, unroot genuinely failed.
cleanup() {
  adb unroot 2>/dev/null || true
  adb wait-for-device 2>/dev/null || true
  if adb shell id 2>/dev/null | grep -q "uid=0"; then
    log_warn "adb unroot may have failed — adbd is still running as root"
  fi
}
trap cleanup EXIT

# adb root restarts adbd. wait-for-device returns once the device state
# transitions to "device", but the shell may not be ready yet.
# Probe until getprop returns a non-empty result.
SDK=""
for _i in $(seq 1 15); do
  SDK="$(adb shell getprop ro.build.version.sdk 2>/dev/null | tr -d '\r' || true)"
  [[ -n "$SDK" ]] && break
  log_info "Waiting for adb shell readiness after root ($_i/15)..."
  sleep 1
done
[[ -n "$SDK" ]] || fatal "adb shell not ready after adb root (timed out)"
adb shell id 2>/dev/null | grep -q "uid=0" || fatal "adb root failed — adbd is not running as root"
log_info "API $SDK — injecting $CERT_BASENAME"

# Injection logic — wrapped in a function so the retry loop can re-run it
# without re-executing adb root / SDK detection. Idempotency checks inside
# mean successful sub-steps are skipped on retry.
inject_ca() {
  local SYSTEM_OK=false USER_OK=false

  if adb shell "[ -f /system/etc/security/cacerts/$CERT_BASENAME ]" 2>/dev/null; then
    if [[ "$SDK" -ge 34 ]]; then
      check_cert_visibility_in_namespaces "$CERT_BASENAME" quiet && SYSTEM_OK=true
    else
      SYSTEM_OK=true
    fi
  fi
  adb shell "[ -f /data/misc/user/0/cacerts-added/$CERT_BASENAME ]" 2>/dev/null && USER_OK=true

  if $SYSTEM_OK && $USER_OK; then
    log_info "Already injected — skipping"
    return 0
  fi

  # On Windows/MSYS2, MSYS converts the device-side path (/data/local/tmp/…) to
  # a Windows path (C:/Program Files/Git/data/…), breaking adb push.
  # MSYS_NO_PATHCONV=1 disables conversion, so we pre-convert the host path
  # to a Windows path ourselves (cygpath -w) so adb can still find the file.
  local _cert_host="$CERT_PATH"
  if command -v cygpath >/dev/null 2>&1; then
    _cert_host="$(cygpath -w "$CERT_PATH")"
  fi
  MSYS_NO_PATHCONV=1 adb push "$_cert_host" "/data/local/tmp/$CERT_BASENAME" >/dev/null || return 1

  # System store injection
  if ! $SYSTEM_OK; then
    if [[ "$SDK" -le 33 ]]; then
      inject_tmpfs_overlay || return 1
    else
      inject_tmpfs_overlay_with_nsenter || return 1
    fi

    if ! adb shell "[ -f /system/etc/security/cacerts/$CERT_BASENAME ]" 2>/dev/null; then
      log_error "Verification failed: cert not in /system/etc/security/cacerts/"
      return 1
    fi

    if [[ "$SDK" -ge 34 ]]; then
      if ! check_cert_visibility_in_namespaces "$CERT_BASENAME"; then
        log_error "Cert not visible in required mount namespaces"
        return 1
      fi
    fi
  fi

  # User cert store — Chrome 121+ treats system-store CAs as public and
  # requires SCTs; user-store CAs are exempt (needed for OAuth/Chrome Custom Tabs).
  if ! $USER_OK; then
    log_info "Installing to user cert store"
    adb shell "su 0 sh -c 'mkdir -p /data/misc/user/0/cacerts-added && \
      cp /data/local/tmp/$CERT_BASENAME /data/misc/user/0/cacerts-added/ && \
      chmod 644 /data/misc/user/0/cacerts-added/$CERT_BASENAME && \
      chown system:system /data/misc/user/0/cacerts-added/$CERT_BASENAME'" || return 1
  fi

  log_info "CA injection complete (system + user store)"
}

# Retry loop — handles transient failures (zygote PID instability, adb flakiness).
# Setup (adb root, SDK detection) runs once above; only injection retries.
MAX_RETRIES="${INJECT_CA_RETRIES:-3}"
for _attempt in $(seq 1 "$MAX_RETRIES"); do
  if inject_ca; then
    exit 0
  fi
  if [[ "$_attempt" -lt "$MAX_RETRIES" ]]; then
    log_warn "CA injection failed (attempt $_attempt/$MAX_RETRIES), retrying in 5s..."
    sleep 5
  fi
done

fatal "CA injection failed after $MAX_RETRIES attempts"
