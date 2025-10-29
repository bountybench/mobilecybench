#!/usr/bin/env bash
# apps/ankidroid/setup.sh
set -euo pipefail

# Always work from this folder (apps/ankidroid/)
cd "$(dirname "$0")"

PKG="com.ichi2.anki"

echo "[setup] 1) Bring up the Anki sync server (Docker Compose)…"
# Uses apps/ankidroid/docker-compose.yml (same folder as this script)
docker compose -f ./docker-compose.yml up -d

echo "[setup] 2) Wait for the server to be ready…"
# Simple wait loop: poll `docker compose ps` for "(healthy)" for up to ~60s.
# If your image doesn't set a healthcheck, this will still pass once 'listening' appears in logs.
for i in {1..30}; do
  if docker compose -f ./docker-compose.yml ps | grep -q "(healthy)"; then
    echo "[setup]    server is healthy"
    break
  fi
  # Fallback: if no healthcheck, detect 'listening' in the service logs
  if docker compose -f ./docker-compose.yml logs --tail=50 anki-sync 2>/dev/null | grep -qi "listening addr="; then
    echo "[setup]    server is listening"
    break
  fi
  sleep 2
  if [[ $i -eq 30 ]]; then
    echo "[setup] WARN: server not marked healthy yet; continuing anyway"
  fi
done

echo "[setup] 3) Ensure we have an APK to install…"
# If apk/ankidroid.apk is missing, build it via your setup_app_source.sh
if [[ ! -f apk/ankidroid.apk ]]; then
  echo "[setup]    apk/ankidroid.apk not found; building from source…"
  bash ./setup_app_source.sh
fi
[[ -f apk/ankidroid.apk ]] || { echo "[setup] ERROR: apk/ankidroid.apk still not found"; exit 1; }

echo "[setup] 4) Wait for an emulator/device, then (re)install the app…"
adb start-server >/dev/null 2>&1 || true
adb wait-for-device

# Clean install to avoid signature/version conflicts
adb uninstall "$PKG" >/dev/null 2>&1 || true
adb install -r -d apk/ankidroid.apk

## Resolve actual installed package (release)
PKG="$(adb shell pm list packages | sed -n 's/package:\(com\.ichi2\.anki[^\r]*\)/\1/p' | head -n1)"
export PKG

# File access
adb shell appops set "$PKG" MANAGE_EXTERNAL_STORAGE allow || \
adb shell appops set --user 0 "$PKG" MANAGE_EXTERNAL_STORAGE allow || true

# Notifications (Android 13+)
adb shell pm grant "$PKG" android.permission.POST_NOTIFICATIONS 2>/dev/null || true

# Optional scoped media (harmless if not needed)
adb shell pm grant "$PKG" android.permission.READ_MEDIA_IMAGES  2>/dev/null || true
adb shell pm grant "$PKG" android.permission.READ_MEDIA_AUDIO   2>/dev/null || true
adb shell pm grant "$PKG" android.permission.READ_MEDIA_VIDEO   2>/dev/null || true

# Restart to apply
adb shell am force-stop "$PKG" || true

echo "[setup] 5) Launch app for initial configuration…"
# Launch the app - manual configuration will be needed or app will use default settings
adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
sleep 2

echo "[setup] Done."
echo "[setup] NOTE: App installed but not configured. Manual configuration or test automation required."