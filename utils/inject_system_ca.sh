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
  # Uses nsenter to bind-mount into zygote and child app mount namespaces.
  log_info "Using API >= 34 method (tmpfs overlay + nsenter bind-mount)"
  adb shell 'su 0 sh -s' <<EOF
set -e
CERT="/data/local/tmp/$CERT_BASENAME"
STORE=/system/etc/security/cacerts
APEX=/apex/com.android.conscrypt/cacerts
TMP=/data/local/tmp/cacerts-copy

snapshot_zygotes() {
  pidof zygote64 zygote 2>/dev/null |
    tr ' ' '\n' |
    awk 'NF' |
    sort -n -u |
    tr '\n' ' ' |
    sed 's/ $//'
}

wait_for_stable_zygotes() {
  PREV=""
  ATTEMPT=1

  while [ "\$ATTEMPT" -le 5 ]; do
    CURR="\$(snapshot_zygotes || true)"
    if [ -n "\$CURR" ] && [ "\$CURR" = "\$PREV" ]; then
      printf '%s\n' "\$CURR"
      return 0
    fi
    PREV="\$CURR"
    ATTEMPT=\$((ATTEMPT + 1))
    sleep 2
  done

  return 1
}

list_child_pids() {
  ps -A -o PID,PPID |
    awk -v z="\$1" 'BEGIN{split(z,a," "); for (i in a) parents[a[i]]=1} \$2 in parents {print \$1}' |
    tr '\n' ' ' |
    sed 's/ $//'
}

dump_pid_diag() {
  TARGET_PID="\$1"
  ps -A -o PID,PPID,NAME | awk -v p="\$TARGET_PID" '\$1 == p {print "process " \$0 > "/dev/stderr"}'
  if [ -e "/proc/\$TARGET_PID/ns/mnt" ]; then
    echo "mount-ns \$(readlink /proc/\$TARGET_PID/ns/mnt)" >&2
  else
    echo "mount-ns missing for pid=\$TARGET_PID" >&2
  fi
}

bind_mount_into_pid() {
  TARGET_PID="\$1"
  ATTEMPT=1

  while [ "\$ATTEMPT" -le 5 ]; do
    if [ ! -e "/proc/\$TARGET_PID/ns/mnt" ]; then
      echo "Skipping pid=\$TARGET_PID because /proc entry vanished before bind-mount" >&2
      return 0
    fi

    if nsenter --mount=/proc/\$TARGET_PID/ns/mnt -- /bin/mount --bind "\$STORE" "\$APEX"; then
      return 0
    fi

    echo "nsenter bind-mount failed for pid=\$TARGET_PID (attempt \$ATTEMPT/5)" >&2
    dump_pid_diag "\$TARGET_PID"
    ATTEMPT=\$((ATTEMPT + 1))
    sleep 2
  done

  return 1
}

# 1. Collect stock certs from APEX
rm -rf "\$TMP"
mkdir -p -m 700 "\$TMP"
cp \$APEX/* "\$TMP"/

# 2. Overlay /system store with tmpfs
mountpoint -q "\$STORE" || mount -t tmpfs tmpfs "\$STORE"
rm -f "\$STORE"/*
cp "\$TMP"/* "\$STORE"/
cp "\$CERT" "\$STORE"/

chown root:root "\$STORE"/*
chmod 644 "\$STORE"/*
chcon u:object_r:system_file:s0 "\$STORE"/*

# 3. Bind-mount into all zygote namespaces + current child app namespaces.
# nsenter can fail transiently (e.g. right after adb root restarts adbd), so retry.
for Z in \$(pidof zygote64 zygote 2>/dev/null || true); do
  [ -n "\$Z" ] || continue
  for attempt in 1 2 3 4 5; do
    if nsenter --mount=/proc/\$Z/ns/mnt -- /bin/mount --bind "\$STORE" "\$APEX" 2>/dev/null; then
      break
    fi
    sleep 2
  done

  for PID in \$(ps -A -o PID,PPID | awk -v z="\$Z" '\$2==z {print \$1}'); do
    nsenter --mount=/proc/\$PID/ns/mnt -- /bin/mount --bind "\$STORE" "\$APEX" 2>/dev/null || true
  done
done

rm -rf "\$TMP"
EOF
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

# Skip if cert already present in both stores (and visible in zygote for API 34+)
SYSTEM_OK=false
USER_OK=false

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
  exit 0
fi

# Push cert to device (needed by both system and user store injection)
adb push "$CERT_PATH" "/data/local/tmp/$CERT_BASENAME" >/dev/null

# System store injection
if ! $SYSTEM_OK; then
  if [[ "$SDK" -le 33 ]]; then
    inject_tmpfs_overlay
  else
    inject_tmpfs_overlay_with_nsenter
  fi

  if ! adb shell "[ -f /system/etc/security/cacerts/$CERT_BASENAME ]" 2>/dev/null; then
    fatal "Verification failed: cert not in /system/etc/security/cacerts/"
  fi

if [[ "$SDK" -ge 34 ]]; then
  visible=0
  for _ in 1 2 3 4 5; do
    while IFS= read -r Z; do
      [[ -n "$Z" ]] || continue
      if adb shell "su 0 nsenter --mount=/proc/$Z/ns/mnt -- ls /apex/com.android.conscrypt/cacerts/$CERT_BASENAME" >/dev/null 2>&1; then
        visible=1
        break 2
      fi
    done < <(adb shell "pidof zygote64 zygote 2>/dev/null || true" | tr ' ' '\n' | tr -d '\r')
    sleep 2
  done
  if [[ "$visible" -ne 1 ]]; then
    fatal "Cert not visible in zygote namespace"
  fi
fi

# Also install to user cert store so Chrome trusts it without CT enforcement.
# Chrome 121+ treats system-store CAs as public and requires SCTs; user-store
# CAs are exempt. This is needed for OAuth flows via Chrome Custom Tabs.
if ! $USER_OK; then
  log_info "Installing to user cert store"
  adb shell "su 0 sh -c 'mkdir -p /data/misc/user/0/cacerts-added && \
    cp /data/local/tmp/$CERT_BASENAME /data/misc/user/0/cacerts-added/ && \
    chmod 644 /data/misc/user/0/cacerts-added/$CERT_BASENAME && \
    chown system:system /data/misc/user/0/cacerts-added/$CERT_BASENAME'"
fi

log_info "CA injection complete (system + user store)"
