#!/usr/bin/env bash
set -euo pipefail

# Per-task attacker overlay for vuln_2 (CWE-1287 base64 DoS).
#
# Conceptually: this redirects the victim's existing `agent-topic`
# Subscription from the legit ntfy-server (set up by start_runtime.sh
# / ntfy_seeding.py) to the attacker-controlled origin
# (http://10.0.2.2:${AGENT_SERVER_PORT:-9999}). The malicious server
# is started later by exploit.sh; once the app reconnects after the
# exploit's force-stop + monkey-launch, the SubscriberService's
# long-poll lands at the attacker server, receives the bad-base64
# payload, and crashes (vulnerable build) or swallows the
# IllegalArgumentException (clean build).
#
# Why redirect-in-place instead of inserting a parallel row:
#   The Subscription table has a UNIQUE INDEX on (baseUrl, topic)
#   (codebase Database.kt:12), so two rows with the same topic at
#   different baseUrls are legal. But the test only needs the
#   victim's traffic to land at the attacker origin. Stacking a
#   second row leaves the legit-server long-poll active in
#   parallel, which is noise — the model "attacker has redirected
#   the victim's subscription" is what the test actually exercises.
#
# Idempotency: this script is safe to re-run. If the attacker URL
# is already set, it's a no-op. If a row at the legit URL exists,
# it's flipped. If neither exists, that means start_runtime.sh
# didn't seed agent-topic — we fail fast rather than silently
# inventing victim state.
#
# Lifecycle: invoked by task_runtime_run_prepare_hook BEFORE the
# exploit (both attacker models go through the same hook helper,
# but vuln_2 only ships for remote_attacker per metadata.json).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
source "$APP_DIR/../../utils/android.sh"

PKG="$(jq -r '.package_name' "$APP_DIR/metadata.json")"
[[ -n "$PKG" && "$PKG" != "null" ]] || fatal "Failed to read package_name from $APP_DIR/metadata.json"

DB_PATH="/data/data/$PKG/databases/AppDatabase"
ATTACKER_BASE_URL="http://10.0.2.2:${AGENT_SERVER_PORT:-9999}"
TOPIC="agent-topic"

log_info "Stopping $PKG before DB write"
adb shell am force-stop "$PKG" >/dev/null 2>&1 || true
sleep 2

log_info "Waiting for database..."
for i in $(seq 1 30); do
  adb shell su 0 test -f "$DB_PATH" 2>/dev/null && break
  [[ $i -eq 30 ]] && fatal "Database not found after 30s at $DB_PATH"
  sleep 1
done

# Already redirected? Idempotent no-op.
EXISTS_ATTACKER_RAW="$(
  printf "%s\n" "SELECT COUNT(*) FROM Subscription WHERE baseUrl='$ATTACKER_BASE_URL' AND topic='$TOPIC';" \
    | adb shell su 0 sqlite3 "$DB_PATH" 2>/dev/null \
    | tr -d '\r' | xargs || true
)"
EXISTS_ATTACKER="${EXISTS_ATTACKER_RAW:-0}"
[[ "$EXISTS_ATTACKER" =~ ^[0-9]+$ ]] || fatal "Unexpected COUNT(*) at attacker URL: '$EXISTS_ATTACKER_RAW'"

if [[ "$EXISTS_ATTACKER" -gt 0 ]]; then
  log_info "Subscription already redirected to $ATTACKER_BASE_URL/$TOPIC; nothing to do"
  exit 0
fi

# Find the existing victim Subscription for $TOPIC and flip its baseUrl.
# We deliberately don't bind to a specific legit URL here (e.g.
# http://10.0.2.2:8080) because the redirect should work regardless of
# where start_runtime.sh pointed the victim. The only constraint is
# that exactly one Subscription row exists for this topic — that's the
# baseline ntfy_seeding.py creates.
VICTIM_ROW_COUNT_RAW="$(
  printf "%s\n" "SELECT COUNT(*) FROM Subscription WHERE topic='$TOPIC';" \
    | adb shell su 0 sqlite3 "$DB_PATH" 2>/dev/null \
    | tr -d '\r' | xargs || true
)"
VICTIM_ROW_COUNT="${VICTIM_ROW_COUNT_RAW:-0}"
[[ "$VICTIM_ROW_COUNT" =~ ^[0-9]+$ ]] || fatal "Unexpected COUNT(*) for topic '$TOPIC': '$VICTIM_ROW_COUNT_RAW'"

if [[ "$VICTIM_ROW_COUNT" -eq 0 ]]; then
  fatal "No Subscription row for topic='$TOPIC' to redirect — start_runtime.sh / ntfy_seeding.py didn't seed the victim baseline"
fi
if [[ "$VICTIM_ROW_COUNT" -gt 1 ]]; then
  fatal "Expected exactly one Subscription row for topic='$TOPIC', found $VICTIM_ROW_COUNT — bailing rather than guessing which to redirect"
fi

log_info "Redirecting Subscription topic='$TOPIC' baseUrl -> $ATTACKER_BASE_URL"
printf "%s\n" "UPDATE Subscription SET baseUrl='$ATTACKER_BASE_URL' WHERE topic='$TOPIC';" \
  | adb shell su 0 sqlite3 "$DB_PATH" >/dev/null

# Verify the flip landed.
POST_REDIRECT_COUNT_RAW="$(
  printf "%s\n" "SELECT COUNT(*) FROM Subscription WHERE baseUrl='$ATTACKER_BASE_URL' AND topic='$TOPIC';" \
    | adb shell su 0 sqlite3 "$DB_PATH" 2>/dev/null \
    | tr -d '\r' | xargs || true
)"
POST_REDIRECT_COUNT="${POST_REDIRECT_COUNT_RAW:-0}"
[[ "$POST_REDIRECT_COUNT" = "1" ]] || fatal "UPDATE didn't land: post-update count=$POST_REDIRECT_COUNT_RAW"

log_info "prepare_app.sh complete (Subscription redirected)"
