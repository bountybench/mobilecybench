#!/usr/bin/env bash
set -euo pipefail

# Adds a CA cert to the Android emulator system trust store so apps
# trust local HTTPS backends (10.0.2.2). Detects API level automatically:
#   API <= 33: tmpfs overlay on /system/etc/security/cacerts
#   API >= 34: tmpfs overlay + nsenter bind-mount into zygote/app namespaces
# Does not require -writable-system or adb remount.

usage() {
  cat <<'EOF'
Usage: inject_system_ca.sh [-s SERIAL] [CERT_PATH]

Add CA cert to emulator system trust store for local HTTPS backends.

Arguments:
  -s SERIAL   ADB serial (optional; auto-detects single device if omitted)
  CERT_PATH   Path to Android-hash cert file (<hash>.0)

Defaults:
  CERT_PATH is auto-discovered from <repo>/tls/*.0
EOF
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=utils/common.sh
source "$SCRIPT_DIR/common.sh"

# ── Injection methods ─────────────────────────────────────────────

inject_api33() {
  log_info "Using API <= 33 method (tmpfs overlay, no namespace injection)"
  adb_sh 'su 0 sh -s' <<EOF
set -e
CERT="/data/local/tmp/$CERT_BASENAME"
STORE=/system/etc/security/cacerts

# Overlay with tmpfs if not already mounted
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

echo "API <= 33: cert injected into system store"
EOF
}

inject_api34() {
  log_info "Using API >= 34 method (tmpfs overlay + nsenter namespace injection)"
  adb_sh 'su 0 sh -s' <<EOF
set -e
CERT="/data/local/tmp/$CERT_BASENAME"
STORE=/system/etc/security/cacerts
APEX=/apex/com.android.conscrypt/cacerts
TMP=/data/local/tmp/cacerts-copy

# 1. Collect all stock certs from APEX (the authoritative source on 14+)
rm -rf "\$TMP"
mkdir -p -m 700 "\$TMP"
cp \$APEX/* "\$TMP"/

# 2. Overlay /system store with tmpfs containing stock + custom cert
mountpoint -q "\$STORE" || mount -t tmpfs tmpfs "\$STORE"
rm -f "\$STORE"/*
cp "\$TMP"/* "\$STORE"/
cp "\$CERT" "\$STORE"/

chown root:root "\$STORE"/*
chmod 644 "\$STORE"/*
chcon u:object_r:system_file:s0 "\$STORE"/*

# 3. Bind-mount into zygote64 + child app namespaces
Z="\$(pidof zygote64)"
nsenter --mount=/proc/\$Z/ns/mnt -- /bin/mount --bind "\$STORE" "\$APEX"

for PID in \$(ps -A -o PID,PPID | awk -v z="\$Z" '\$2==z {print \$1}'); do
  nsenter --mount=/proc/\$PID/ns/mnt -- /bin/mount --bind "\$STORE" "\$APEX" 2>/dev/null || true
done

rm -rf "\$TMP"
echo "API >= 34: cert injected with namespace bind-mounts"
EOF
}

# ── Args ──────────────────────────────────────────────────────────
SERIAL=""
CERT_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    -s)
      [[ $# -ge 2 ]] || fatal "Missing value for -s"
      SERIAL="$2"
      shift 2
      ;;
    *)  CERT_PATH="$1"; shift ;;
  esac
done

# ── ADB helpers ───────────────────────────────────────────────────
ADB=(adb)
if [[ -n "$SERIAL" ]]; then
  ADB=(adb -s "$SERIAL")
fi

adb_sh() { "${ADB[@]}" shell "$@"; }

require_cmd adb

# Default cert: first *.0 file in tls/
if [[ -z "$CERT_PATH" ]]; then
  CERT_PATH="$(ls "$REPO_ROOT"/tls/*.0 2>/dev/null | head -1 || true)"
fi
if [[ -z "$CERT_PATH" ]]; then
  fatal "No cert found. Provide path or place <hash>.0 in tls/"
fi
[[ -f "$CERT_PATH" ]] || fatal "Cert file not found: $CERT_PATH"

CERT_BASENAME="$(basename "$CERT_PATH")"

# ── Pre-flight ────────────────────────────────────────────────────
log_info "Cert: $CERT_PATH ($CERT_BASENAME)"
log_info "Device: $SERIAL"

"${ADB[@]}" root 2>/dev/null || true
"${ADB[@]}" wait-for-device >/dev/null

SDK="$(adb_sh getprop ro.build.version.sdk | tr -d '\r')"
[[ -n "$SDK" ]] || fatal "Could not detect SDK version"
log_info "Detected API level: $SDK"

# ── Idempotency check ────────────────────────────────────────────
if adb_sh "[ -f /system/etc/security/cacerts/$CERT_BASENAME ]" 2>/dev/null; then
  if [[ "$SDK" -ge 34 ]]; then
    Z="$(adb_sh pidof zygote64 | tr -d '\r' || true)"
    if [[ -n "$Z" ]] && adb_sh "nsenter --mount=/proc/$Z/ns/mnt -- ls /apex/com.android.conscrypt/cacerts/$CERT_BASENAME" >/dev/null 2>&1; then
      log_info "Cert already injected and visible in zygote namespace — skipping"
      exit 0
    fi
  else
    log_info "Cert already injected — skipping"
    exit 0
  fi
fi

# ── Push cert to device ──────────────────────────────────────────
"${ADB[@]}" push "$CERT_PATH" "/data/local/tmp/$CERT_BASENAME" >/dev/null
log_info "Pushed cert to device"

# ── Inject ────────────────────────────────────────────────────────
if [[ "$SDK" -le 33 ]]; then
  inject_api33
else
  inject_api34
fi

# ── Verify ────────────────────────────────────────────────────────
log_info "Verifying injection..."

if ! adb_sh "ls /system/etc/security/cacerts/$CERT_BASENAME" >/dev/null 2>&1; then
  fatal "Verification failed: cert not found in /system/etc/security/cacerts/"
fi

if [[ "$SDK" -ge 34 ]]; then
  Z="$(adb_sh pidof zygote64 | tr -d '\r' || true)"
  if [[ -n "$Z" ]]; then
    if adb_sh "nsenter --mount=/proc/$Z/ns/mnt -- ls /apex/com.android.conscrypt/cacerts/$CERT_BASENAME" >/dev/null 2>&1; then
      log_info "Verified: cert visible in zygote namespace"
    else
      log_warn "Cert in /system store but NOT visible in zygote namespace"
      exit 1
    fi
  fi
fi

log_info "System CA injection complete"
