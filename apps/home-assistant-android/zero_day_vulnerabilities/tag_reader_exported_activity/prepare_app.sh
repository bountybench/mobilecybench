#!/usr/bin/env bash
set -euo pipefail

: "${MCB_OUTPUT_DIR:?MCB_OUTPUT_DIR is required}"

LOG_DIR="$MCB_OUTPUT_DIR/verifier_logcat"
LOG_FILE="$LOG_DIR/logcat.txt"
PID_FILE="$LOG_DIR/logcat.pid"

log() {
  echo "[prepare_app] $*"
}

if [ -f "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null | tr -d '\r\n' || true)"
  if [ -n "$old_pid" ]; then
    kill "$old_pid" >/dev/null 2>&1 || true
  fi
fi

rm -rf "$LOG_DIR"
mkdir -p "$LOG_DIR"

log "Starting verifier-owned logcat capture at $LOG_FILE"
adb logcat -c
nohup adb logcat -b main -b system -b crash -v threadtime >"$LOG_FILE" 2>&1 &
echo "$!" > "$PID_FILE"
sleep 1

if ! kill -0 "$(cat "$PID_FILE")" >/dev/null 2>&1; then
  echo "[prepare_app] ERROR: logcat capture failed to stay running" >&2
  exit 1
fi

log "prepare_app.sh complete"
