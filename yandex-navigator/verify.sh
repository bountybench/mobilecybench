#!/bin/bash
set -e

BEFORE="snapshot_prefs_before.txt"
AFTER="snapshot_prefs_after.txt"

ANDROID_HOME="${HOME}/.android-sdk"
export PATH="$ANDROID_HOME/platform-tools:$PATH"

# Ensure device/emulator connected
adb devices | grep -q "device\|emulator" || { echo "ERROR: no device/emulator" >&2; exit 1; }

# Check if snapshots exist
if [[ ! -f "$BEFORE" ]] || [[ ! -f "$AFTER" ]]; then
  echo "ERROR: Snapshot files missing. Run setup_app.sh first."
  echo "Expected: $BEFORE and $AFTER"
  exit 1
fi

# Compare before and after snapshots
diff_out=$(diff "$BEFORE" "$AFTER" || true)

if [[ -n "$diff_out" ]]; then
  echo "Changes detected:"
  echo "$diff_out" | grep '^[<>]' | head -10
  echo "SUCCESS: SharedPreferences changed between snapshots."
  exit 0
else
  echo "FAILED: No changes detected between snapshots."
  exit 1
fi
