#!/usr/bin/env bash
set -euo pipefail

TARGET_PACKAGE="com.audiobookshelf.app"
TARGET_ACTIVITY="${TARGET_PACKAGE}/.MainActivity"

# Source the victim password from secrets.json so a rotation can't leave
# a stale hardcoded literal that silently breaks the UI login. Caller
# env var still wins.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_PATH="${SCRIPT_DIR}/secrets.json"

: "${ABS_SERVER_URL:=http://10.0.2.2:13378}"
: "${ABS_VICTIM_USERNAME:=root}"
if [[ -z "${ABS_VICTIM_PASSWORD:-}" ]]; then
    if ! command -v jq >/dev/null 2>&1; then
        echo "ABS_VICTIM_PASSWORD not set and jq not on PATH" >&2
        exit 2
    fi
    if [[ ! -f "$SECRETS_PATH" ]]; then
        echo "ABS_VICTIM_PASSWORD not set and secrets.json not found at $SECRETS_PATH" >&2
        exit 2
    fi
    ABS_VICTIM_PASSWORD=$(jq -r '.ADMIN_PASSWORD' "$SECRETS_PATH")
    if [[ -z "$ABS_VICTIM_PASSWORD" || "$ABS_VICTIM_PASSWORD" == "null" ]]; then
        echo "secrets.json missing ADMIN_PASSWORD" >&2
        exit 2
    fi
fi

dump_ui() {
  adb exec-out uiautomator dump /dev/tty 2>/dev/null | tr -d '\r'
}

ui_center_for() {
  local mode="$1"
  local needle="$2"

  UI_MODE="$mode" UI_NEEDLE="$needle" python3 -c '
import os
import re
import sys
import xml.etree.ElementTree as ET

xml = sys.stdin.read()
start = xml.find("<?xml")
end = xml.rfind("</hierarchy>")
if start < 0 or end < 0:
    raise SystemExit(1)
xml = xml[start:end + len("</hierarchy>")]
root = ET.fromstring(xml)
mode = os.environ["UI_MODE"]
needle = os.environ["UI_NEEDLE"]
matches = []

for node in root.iter("node"):
    if mode == "text" and node.get("text") != needle:
        continue
    if mode == "class" and node.get("class") != needle:
        continue
    bounds = node.get("bounds", "")
    nums = [int(x) for x in re.findall(r"\d+", bounds)]
    if len(nums) != 4:
        continue
    matches.append(((nums[0] + nums[2]) // 2, (nums[1] + nums[3]) // 2))

if not matches:
    raise SystemExit(1)

index = 0
if mode == "class":
    index = int(os.environ.get("UI_INDEX", "0"))
    if index >= len(matches):
        raise SystemExit(1)

print(*matches[index])
' <<<"$(dump_ui)"
}

ui_has_text() {
  local text="$1"
  dump_ui | grep -Fq "$text"
}

count_edit_texts() {
  dump_ui | grep -o 'class="android.widget.EditText"' | wc -l
}

wait_for_login_form() {
  local timeout="${1:-20}"
  for _ in $(seq 1 "$timeout"); do
    if [[ "$(count_edit_texts)" -ge 2 ]]; then
      return 0
    fi
    if ui_has_text "Failed to contact server"; then
      return 2
    fi
    sleep 1
  done
  return 1
}

wait_for_ui_text() {
  local text="$1"
  local timeout="${2:-20}"

  for _ in $(seq 1 "$timeout"); do
    if ui_has_text "$text"; then
      return 0
    fi
    sleep 1
  done

  return 1
}

tap() {
  adb shell input tap "$1" "$2"
}

tap_text() {
  local coords
  coords=$(ui_center_for text "$1")
  tap ${coords% *} ${coords#* }
}

tap_edit_text() {
  local coords
  coords=$(UI_INDEX="$1" ui_center_for class "android.widget.EditText")
  tap ${coords% *} ${coords#* }
}

enter_text() {
  local text="$1"
  text=${text// /%s}
  text=${text//\'/\'\\\'\'}
  adb shell "input text '$text'"
}

main() {
  adb shell am force-stop "$TARGET_PACKAGE" >/dev/null 2>&1 || true
  adb shell am start -n "$TARGET_ACTIVITY" >/dev/null

  if ! wait_for_ui_text "Server address" 5 && ! ui_has_text "$ABS_SERVER_URL"; then
    wait_for_ui_text "Connect" 20 || {
      echo "Timed out waiting for Audiobookshelf connect screen" >&2
      exit 1
    }
    tap_text "Connect"
  fi

  wait_for_ui_text "Server address" 20 || {
    echo "Timed out waiting for Audiobookshelf server form" >&2
    exit 1
  }

  tap_edit_text 0
  enter_text "$ABS_SERVER_URL"
  adb shell input keyevent KEYCODE_BACK >/dev/null 2>&1 || true
  sleep 0.5
  tap_text "Submit"

  # Wait for the login form (2 EditTexts) instead of waiting for the
  # URL text — wait_for_ui_text "$ABS_SERVER_URL" false-positives on
  # the URL still sitting in the server-form EditText when submission
  # fails, and the script then types the username into the URL field.
  case "$(wait_for_login_form 20; echo $?)" in
    0) ;;
    2)
      echo "Audiobookshelf rejected the server URL '$ABS_SERVER_URL'" >&2
      dump_ui >&2
      exit 1
      ;;
    *)
      echo "Timed out waiting for Audiobookshelf login form" >&2
      dump_ui >&2
      exit 1
      ;;
  esac

  tap_edit_text 0
  enter_text "$ABS_VICTIM_USERNAME"

  tap_edit_text 1
  enter_text "$ABS_VICTIM_PASSWORD"

  adb shell input keyevent KEYCODE_BACK >/dev/null 2>&1 || true
  sleep 0.5
  tap_text "Submit"

  wait_for_ui_text "Home" 20 || {
    if ui_has_text "Failed to login"; then
      echo "Audiobookshelf rejected the victim credentials" >&2
    fi
    echo "Timed out waiting for Audiobookshelf home screen after login" >&2
    exit 1
  }
}

main "$@"
