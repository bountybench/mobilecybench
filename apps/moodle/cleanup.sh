#!/usr/bin/env bash
# Cleanup script: full teardown of containers, volumes, manifests, and logs.
# Usage: ./cleanup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Cleaning up Docker containers/images"

docker compose down
docker rm -f temp-builder 2>/dev/null || echo "Container temp-builder not found"
docker rmi -f moodle-builder 2>/dev/null || echo "Image moodle-builder not found"
docker rmi -f moodlehq/moodle-php-apache 2>/dev/null || echo "Image moodle-php-apache not found"


# Remove reports and scores for clean runs
if [[ -d "${SCRIPT_DIR}/.reports" ]]; then
  echo "Removing reports directory"
  rm -rf -- "${SCRIPT_DIR}/.reports"
fi
if [[ -f "${SCRIPT_DIR}/scores.json" ]]; then
  echo "Removing scores.json"
  rm -f -- "${SCRIPT_DIR}/scores.json"
fi

# Remove logs
echo "Removing runtime logs"
rm -f -- "${SCRIPT_DIR}"/*agent_log*.log 2>/dev/null || true
rm -f -- "${SCRIPT_DIR}"/setup_app_apklink.log 2>/dev/null || true
rm -f -- "${SCRIPT_DIR}"/setup_app_source.log 2>/dev/null || true

adb uninstall com.moodle.moodlemobile 2>/dev/null || true

# EC-010: purge per-run host markers so partial state from an aborted
# prepare_victim does not pollute the next run. Markers live in /tmp
# with the .mcb_moodle_ prefix.
echo "Removing per-run host markers from /tmp"
rm -f -- /tmp/.mcb_moodle_* 2>/dev/null || true

echo "Cleanup complete"