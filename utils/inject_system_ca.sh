#!/usr/bin/env bash
set -euo pipefail

# inject_system_ca.sh — Add a CA cert to the Android emulator system trust store
# so apps trust local HTTPS backends (e.g. 10.0.2.2).
#
# Android apps only trust system CAs for HTTPS. Our local TLS proxy uses a
# self-signed CA, so we inject it into the emulator's system trust store at runtime.
# This avoids modifying the app's network_security_config.xml or using -writable-system.
#
# The script uses a tmpfs overlay on /system/etc/security/cacerts — the original partition
# stays read-only, and the overlay is lost on reboot. So the cert doesn't persist across reboots.
# No reboot required — the cert is visible to apps immediately after injection.
#
# API-level handling:
#   API <= 33: tmpfs overlay is sufficient; apps read from /system/etc/security/cacerts.
#   API >= 34: Android 14+ moved CA certs to /apex/com.android.conscrypt/cacerts with
#     per-process mount namespaces. The tmpfs overlay alone isn't visible to apps.
#     We use nsenter to bind-mount the overlay into the zygote and all running app
#     mount namespaces, based on the technique from:
#     https://httptoolkit.com/blog/android-14-install-system-ca-certificate/
#
# Idempotent: skips injection if the cert is already present and visible.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=utils/common.sh
source "$SCRIPT_DIR/common.sh"


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
  # Uses nsenter to bind-mount into zygote64 and all child app mount namespaces.
  log_info "Using API >= 34 method (tmpfs overlay + nsenter bind-mount)"
  adb shell 'su 0 sh -s' <<EOF
set -e
CERT="/data/local/tmp/$CERT_BASENAME"
STORE=/system/etc/security/cacerts
APEX=/apex/com.android.conscrypt/cacerts
TMP=/data/local/tmp/cacerts-copy

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

# 3. Bind-mount into zygote64 + child app namespaces
# nsenter can fail transiently (e.g. after adb root restarts adbd) — retry.
Z="\$(pidof zygote64)"
for attempt in 1 2 3; do
  if nsenter --mount=/proc/\$Z/ns/mnt -- /bin/mount --bind "\$STORE" "\$APEX" 2>/dev/null; then
    break
  fi
  sleep 2
done

for PID in \$(ps -A -o PID,PPID | awk -v z="\$Z" '\$2==z {print \$1}'); do
  nsenter --mount=/proc/\$PID/ns/mnt -- /bin/mount --bind "\$STORE" "\$APEX" 2>/dev/null || true
done

rm -rf "\$TMP"
EOF
}

# Find cert: use arg if provided, otherwise auto-discover from tls/
CERT_PATH="${1:-$(ls "$REPO_ROOT"/tls/*.0 2>/dev/null | head -1 || true)}"
[[ -n "$CERT_PATH" && -f "$CERT_PATH" ]] || fatal "No cert found. Place <hash>.0 in tls/"
CERT_BASENAME="$(basename "$CERT_PATH")"

# Ensure adb root access.
# "adb root" restarts adbd, which drops TCP connections (e.g. localhost:5555).
# Over TCP, "adb root" hangs forever waiting for a response that never comes
# because the connection is already dead. Use a timeout to prevent this.
# The script uses "su 0" for all privileged operations, so root adbd is
# nice-to-have but not required.
log_info "[debug] ANDROID_SERIAL=${ANDROID_SERIAL:-<unset>}"
log_info "[debug] step: adb root"
timeout 5 adb root 2>/dev/null || true
if [[ "${ANDROID_SERIAL:-}" == *":"* ]]; then
  log_info "[debug] step: reconnect after adb root (TCP mode)"
  sleep 3
  adb connect "$ANDROID_SERIAL" 2>&1 || true
fi
log_info "[debug] step: adb wait-for-device"
adb wait-for-device >/dev/null
log_info "[debug] step: adb wait-for-device done"

log_info "[debug] step: getprop SDK"
SDK="$(adb shell getprop ro.build.version.sdk | tr -d '\r')"
[[ -n "$SDK" ]] || fatal "Could not detect SDK version"
log_info "API $SDK — injecting $CERT_BASENAME"

# Idempotency: skip if cert already present (and visible in zygote for API 34+)
log_info "[debug] step: idempotency check"
if adb shell "[ -f /system/etc/security/cacerts/$CERT_BASENAME ]" 2>/dev/null; then
  if [[ "$SDK" -ge 34 ]]; then
    Z="$(adb shell pidof zygote64 | tr -d '\r' || true)"
    if [[ -n "$Z" ]] && adb shell "nsenter --mount=/proc/$Z/ns/mnt -- ls /apex/com.android.conscrypt/cacerts/$CERT_BASENAME" >/dev/null 2>&1; then
      log_info "Already injected — skipping"
      exit 0
    fi
  else
    log_info "Already injected — skipping"
    exit 0
  fi
fi

# Push and inject
log_info "[debug] step: adb push"
adb push "$CERT_PATH" "/data/local/tmp/$CERT_BASENAME" >/dev/null
log_info "[debug] step: push done, injecting (SDK=$SDK)"

if [[ "$SDK" -le 33 ]]; then
  inject_tmpfs_overlay
else
  inject_tmpfs_overlay_with_nsenter
fi

# Verify
log_info "[debug] step: verify"
if ! adb shell "[ -f /system/etc/security/cacerts/$CERT_BASENAME ]" 2>/dev/null; then
  fatal "Verification failed: cert not in /system/etc/security/cacerts/"
fi

if [[ "$SDK" -ge 34 ]]; then
  Z="$(adb shell pidof zygote64 | tr -d '\r' || true)"
  if [[ -n "$Z" ]] && ! adb shell "nsenter --mount=/proc/$Z/ns/mnt -- ls /apex/com.android.conscrypt/cacerts/$CERT_BASENAME" >/dev/null 2>&1; then
    fatal "Cert not visible in zygote namespace"
  fi
fi

log_info "System CA injection complete"
