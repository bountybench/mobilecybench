#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

# Waits for a command's output to match a regex pattern.
wait_for_output() {
  local cmd="$1"
  local match="$2"
  local timeout=${3:-30}
  local start_time=$(date +%s)
  local end_time=$((start_time + timeout))
  while true; do
    if bash -c "$cmd" 2>/dev/null | grep -q -E "$match"; then
      printf '\n'
      return 0
    fi
    if (( $(date +%s) >= end_time )); then
      printf '\n' >&2
      printf 'timeout waiting for pattern "%s" from command: %s\n' "$match" "$cmd" >&2
      return 1
    fi
    printf '.'
    sleep 0.5
  done
}