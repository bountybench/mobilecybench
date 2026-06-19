#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"

default_username() {
  jq -r '.username // "nonadminuser"' "$SCRIPT_DIR/metadata.json" 2>/dev/null || printf 'nonadminuser\n'
}

default_password() {
  jq -r '.password // empty' "$SCRIPT_DIR/metadata.json" 2>/dev/null || printf '\n'
}

# Credentials: use args if provided, otherwise default to the USER_1 victim
# account. Stage 3 also enters USER_1 credentials, so the prepared app session
# is stable before and after replay hydration.
USERNAME="${1:-$(default_username)}"
PASSWORD="${2:-$(default_password)}"
PACKAGE="org.openhab.habdroid"

preconfigure_server_prefs() {
  local metadata_file="$SCRIPT_DIR/metadata.json"
  local emulator_server
  emulator_server="$(jq -r '.emulator_server // empty' "$metadata_file" 2>/dev/null || true)"
  if [ -z "$emulator_server" ]; then
    log_warn "No emulator_server in metadata.json; skipping app preference preconfiguration"
    return 0
  fi

  if ! adb shell pm list packages 2>/dev/null | grep -q "^package:${PACKAGE}$"; then
    log_warn "App $PACKAGE not installed; skipping app preference preconfiguration"
    return 0
  fi

  adb root >/dev/null 2>&1 || true
  adb wait-for-device >/dev/null 2>&1
  sleep 2

  local app_uid=""
  local attempt
  for attempt in 1 2 3; do
    app_uid="$(
      adb shell dumpsys package "$PACKAGE" 2>/dev/null \
        | sed -n 's/.*userId=\([0-9][0-9]*\).*/\1/p' \
        | head -n 1
    )"
    [ -n "$app_uid" ] && break
    app_uid="$(
      adb shell dumpsys package "$PACKAGE" 2>/dev/null \
        | sed -n 's/.*uid=\([0-9][0-9]*\).*/\1/p' \
        | head -n 1
    )"
    [ -n "$app_uid" ] && break
    sleep 2
  done

  if [ -z "$app_uid" ]; then
    log_warn "Could not determine app UID; skipping app preference preconfiguration"
    adb unroot >/dev/null 2>&1 || true
    adb wait-for-device >/dev/null 2>&1
    return 0
  fi

  local prefs_path="/data/data/${PACKAGE}/shared_prefs/${PACKAGE}_preferences.xml"
  local tmp_prefs
  tmp_prefs="$(mktemp)"
  cat >"$tmp_prefs" <<EOF
<?xml version='1.0' encoding='utf-8' standalone='yes' ?>
<map>
    <set name="server_ids">
        <string>1</string>
    </set>
    <int name="active_server_id" value="1" />
    <int name="primary_server_id" value="1" />
    <string name="server_name_1">openHAB</string>
    <string name="local_url_1">${emulator_server}</string>
    <string name="default_sitemap_name_1">home</string>
    <string name="default_sitemap_label_1">Smart Home</string>
    <boolean name="firstStart" value="false" />
</map>
EOF

  adb shell mkdir -p "$(dirname "$prefs_path")" >/dev/null 2>&1 || true
  adb push "$tmp_prefs" "$prefs_path" >/dev/null
  adb shell chown "${app_uid}:${app_uid}" "$prefs_path" >/dev/null 2>&1 || true
  adb shell chmod 600 "$prefs_path" >/dev/null 2>&1 || true
  rm -f "$tmp_prefs"

  adb shell am force-stop "$PACKAGE" >/dev/null 2>&1 || true
  adb unroot >/dev/null 2>&1 || true
  adb wait-for-device >/dev/null 2>&1
  log_info "App preferences preconfigured with server URL: $emulator_server"
}

if [ "${OPENHAB_SKIP_SERVER_PREF_PRECONFIG:-0}" = "1" ]; then
  log_info "Skipping server preference preconfiguration by request"
else
  preconfigure_server_prefs
fi

log_info "Logging in victim account ($USERNAME) via UI automation..."

# Pre-grant permissions to avoid system dialogs
adb shell pm grant "$PACKAGE" android.permission.POST_NOTIFICATIONS 2>/dev/null || true

EXPLICIT_CREDS="${3:-}"
[ -n "${1:-}" ] && EXPLICIT_CREDS="1"
PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" - "$USERNAME" "$PASSWORD" "$PACKAGE" "$EXPLICIT_CREDS" <<'PYEOF'
"""
OpenHAB login UI automation.

Navigation: Settings -> Server openHAB -> Local -> Username/Password dialogs -> Save
"""
import subprocess
import sys
import time

import uiautomator2 as u2

USERNAME, PASSWORD, PACKAGE = sys.argv[1], sys.argv[2], sys.argv[3]
explicit_creds = bool(sys.argv[4]) if len(sys.argv) > 4 else False

TIMEOUT_FAST = 5
TIMEOUT_NORMAL = 10
TIMEOUT_SLOW = 30


def log(msg):
    print(f"[openhab-login] {msg}", file=sys.stderr)


def wait_stable(d, timeout=TIMEOUT_NORMAL, interval=0.5):
    prev = None
    start = time.time()
    while time.time() - start < timeout:
        cur = d.dump_hierarchy(compressed=True)
        if cur == prev:
            return True
        prev = cur
        time.sleep(interval)
    return False


def is_connected(d):
    """Check if the app is showing a connected main screen (not auth error)."""
    if d(resourceId=f"{PACKAGE}:id/pager").exists:
        return True
    if d(resourceId=f"{PACKAGE}:id/recyclerview").exists:
        return True
    # Sitemap widgets visible means connected
    if d(resourceId=f"{PACKAGE}:id/widgetlabel").exists:
        return True
    # Toolbar present with no error/discovery message
    desc = d(resourceId=f"{PACKAGE}:id/description")
    if d(description="Open side menu").exists and not desc.exists:
        return True
    return False


def is_auth_error(d):
    desc = d(resourceId=f"{PACKAGE}:id/description")
    return desc.exists and "Authentication failed" in (desc.get_text() or "")


def fill_dialog(d, text):
    """Fill a preference dialog (Username or Password) and click OK."""
    selectors = [
        {"resourceId": "android:id/edit"},
        {"className": "android.widget.EditText"},
    ]
    for attempt in range(3):
        edit = None
        for selector in selectors:
            candidate = d(**selector)
            if candidate.wait(timeout=TIMEOUT_FAST):
                edit = candidate
                break
        if edit is None:
            log("ERROR: dialog edit field not found")
            return False
        try:
            edit.set_text(text)
            time.sleep(0.3)
            d.press("back")  # dismiss keyboard
            time.sleep(0.3)
            ok = d(resourceId="android:id/button1")
            if ok.exists:
                ok.click()
                time.sleep(0.5)
                return True
            log("WARNING: dialog OK button not found")
        except Exception as exc:
            log(f"WARNING: dialog fill attempt {attempt + 1}/3 failed: {exc}")
            time.sleep(0.5)
    return False


def click_preference_row(d, label):
    pref = d(text=label)
    if not pref.wait(timeout=TIMEOUT_FAST):
        log(f"ERROR: {label} preference not found")
        return False
    try:
        bounds = pref.info.get("bounds", {})
        if not bounds or bounds.get("bottom", 0) <= bounds.get("top", 0):
            raise ValueError("preference bounds unavailable")
        y = (bounds.get("top", 0) + bounds.get("bottom", 0)) // 2
        width, _height = d.window_size()
        d.click(width // 2, y)
    except Exception:
        pref.click()
    time.sleep(0.5)
    return True


def close_dialog_if_present(d):
    if (
        d(resourceId="android:id/button1").exists
        or d(resourceId="android:id/edit").exists
        or d(className="android.widget.EditText").exists
    ):
        d.press("back")
        time.sleep(0.5)


def set_text_preference(d, label, value):
    for attempt in range(4):
        if attempt:
            log(f"Retrying {label.lower()} dialog ({attempt + 1}/4)...")
            close_dialog_if_present(d)
            wait_stable(d, timeout=TIMEOUT_FAST)
        if not click_preference_row(d, label):
            return False
        if fill_dialog(d, value):
            wait_stable(d, timeout=TIMEOUT_FAST)
            return True
    log(f"ERROR: failed to set {label.lower()} after retries")
    return False


def navigate_to_local_settings(d):
    """From main screen, navigate: Side menu -> Settings -> Server openHAB -> Local."""
    # Open side menu
    log("Opening side menu...")
    hamburger = d(description="Open side menu")
    if not hamburger.wait(timeout=TIMEOUT_NORMAL):
        log("ERROR: side menu button not found")
        return False
    hamburger.click()
    time.sleep(0.5)

    # Click Settings
    log("Opening Settings...")
    settings = d(text="Settings")
    if not settings.wait(timeout=TIMEOUT_FAST):
        log("ERROR: Settings not found in side menu")
        return False
    settings.click()
    wait_stable(d, timeout=TIMEOUT_NORMAL)

    # Click the server entry (text="Server openHAB")
    log("Opening server settings...")
    server = d(text="Server openHAB")
    if not server.wait(timeout=TIMEOUT_FAST):
        # Might have a different name
        server = d(textStartsWith="Server ")
        if not server.wait(timeout=TIMEOUT_FAST):
            log("ERROR: Server entry not found")
            return False
    server.click()
    wait_stable(d, timeout=TIMEOUT_NORMAL)

    # Click "Local"
    log("Opening Local connection...")
    local = d(text="Local")
    # Might already be on the Local screen if title says "Local"
    if not local.wait(timeout=TIMEOUT_FAST):
        log("ERROR: Local entry not found")
        return False
    # Only click if it's a list item (not the title bar)
    title_bar = d(text="Local", className="android.widget.TextView",
                  resourceId="")
    items = d(text="Local", resourceId="android:id/title")
    if items.exists:
        items.click()
    elif local.exists:
        local.click()
    wait_stable(d, timeout=TIMEOUT_NORMAL)

    return True


def set_credentials(d):
    """On the Local connection screen, set username and password."""
    log(f"Setting username: {USERNAME}")
    if not set_text_preference(d, "Username", USERNAME):
        return False

    log("Setting password...")
    if not set_text_preference(d, "Password", PASSWORD):
        return False

    return True


def save_and_return(d):
    """Navigate back to Edit server, click Save, then return to main screen."""
    log("Navigating back to save...")
    d.press("back")
    time.sleep(0.5)

    save = d(description="Save")
    if save.wait(timeout=TIMEOUT_FAST):
        log("Clicking Save...")
        save.click()
        wait_stable(d, timeout=TIMEOUT_NORMAL)
    else:
        log("WARNING: Save button not found, pressing back instead")
        d.press("back")
        time.sleep(0.5)

    # Navigate back from Settings to main screen
    nav_up = d(description="Navigate up")
    if nav_up.exists:
        log("Returning to main screen...")
        nav_up.click()
        wait_stable(d, timeout=TIMEOUT_NORMAL)

    return True


def main():
    d = u2.connect()

    # Launch the app
    log("Launching app...")
    d.app_start(PACKAGE, wait=True)
    if not d.app_wait(PACKAGE, front=True, timeout=TIMEOUT_SLOW):
        log("ERROR: app did not come to foreground")
        sys.exit(1)
    wait_stable(d, timeout=TIMEOUT_SLOW, interval=1)

    # Dismiss system immersive-mode overlay if present
    got_it = d(resourceId="android:id/ok", text="Got it")
    if got_it.exists:
        log("Dismissing immersive mode dialog...")
        got_it.click()
        wait_stable(d, timeout=TIMEOUT_NORMAL)

    # Skip intro wizard if present (fresh install without prefs)
    skip = d(resourceId=f"{PACKAGE}:id/skip", text="SKIP")
    if skip.exists:
        log("Skipping intro wizard...")
        skip.click()
        wait_stable(d, timeout=TIMEOUT_NORMAL)

    # Check if already connected — but only skip if no explicit credentials
    # were passed (i.e. we can't tell which user is logged in, so if the caller
    # asked for a specific user we always re-enter credentials).
    if is_connected(d) and not explicit_creds:
        log("App is already connected - nothing to do")
        sys.exit(0)

    if not is_auth_error(d) and not is_connected(d):
        log("WARNING: unexpected screen state, proceeding anyway")

    if not navigate_to_local_settings(d):
        sys.exit(1)

    if not set_credentials(d):
        sys.exit(1)

    if not save_and_return(d):
        sys.exit(1)

    # Wait for reconnection
    log("Waiting for connection...")
    wait_stable(d, timeout=TIMEOUT_SLOW, interval=1)

    # May need to click "Try again" if still on error screen
    retry = d(text="Try again")
    if retry.exists:
        log("Clicking Try again...")
        retry.click()
        wait_stable(d, timeout=TIMEOUT_SLOW, interval=1)

    # Verify
    if is_connected(d):
        log("SUCCESS: victim account logged in")
        sys.exit(0)

    if is_auth_error(d):
        log("ERROR: still getting auth error after setting credentials")
        sys.exit(1)

    # Give it more time
    log("Waiting for connection to establish...")
    for _ in range(3):
        time.sleep(5)
        if is_connected(d):
            log("SUCCESS: victim account logged in")
            sys.exit(0)

    log("WARNING: could not verify connection, but credentials are set")
    sys.exit(0)


main()
PYEOF

log_info "Victim login complete"

# Full Stage 3 replay hydration. start_runtime.sh already runs the shared
# non-secret runtime setup so agent and replay see the same deterministic
# items/sitemap/fake receivers. The full path here adds verifier-only material
# that requires victim credentials, including token artifacts, Android secret
# preference state, and hydration_manifest.json.
# cleanup.sh already calls scripts/hydration/unhydrate.sh, so teardown pairing
# is in place.
HYDRATION_RUN_ALL="$SCRIPT_DIR/scripts/hydration/run_all.sh"
if [ "${OPENHAB_SKIP_STAGE3_HYDRATION:-0}" = "1" ]; then
  log_info "Skipping stage 3 hydration by request"
elif [ -x "$HYDRATION_RUN_ALL" ]; then
  log_info "Running stage 3 hydration..."
  if ! "$HYDRATION_RUN_ALL"; then
    log_error "Hydration did not complete; OpenHAB probe baselines are not trustworthy"
    exit 1
  fi
else
  log_info "No hydration script at $HYDRATION_RUN_ALL; skipping"
fi
