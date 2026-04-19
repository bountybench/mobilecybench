#!/usr/bin/env bash
# Cleanup script: full teardown of containers, volumes, manifests, and logs.
# Usage: ./cleanup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Cleaning up Docker containers/images"

# Only touch docker if the daemon is responsive; this script also runs as a
# preflight cleanup before the runtime is up, where `docker info` may fail.
if docker info >/dev/null 2>&1; then
  docker compose down 2>/dev/null || echo "No compose services to stop"
  docker rm -f temp-builder 2>/dev/null || echo "Container temp-builder not found"
  docker rmi -f moodle-builder 2>/dev/null || echo "Image moodle-builder not found"
  docker rmi -f moodlehq/moodle-php-apache 2>/dev/null || echo "Image moodle-php-apache not found"
else
  echo "Docker daemon not available, skipping container cleanup"
fi


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

# Only run adb if a device is actually connected; preflight cleanup runs
# before the emulator boots, where adb has no device to target.
if command -v adb >/dev/null 2>&1 && adb get-state >/dev/null 2>&1; then
  adb uninstall com.moodle.moodlemobile 2>/dev/null || true
fi

echo "Cleanup complete"