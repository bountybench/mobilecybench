#!/bin/bash
set -e

# Function to remove config files with proper permissions in CI environments
remove_config_files_for_ci() {
    # Only use sudo in CI/GitHub Actions environments where we need elevated permissions
    if [[ -n "${CI:-}" || -n "${GITHUB_ACTIONS:-}" ]]; then
        echo "CI environment detected, removing config files with sudo..."
        sudo chmod -R u+w config && sudo rm -rf config
    else
        echo "Non-CI environment, removing config files without sudo..."
        chmod -R u+w config 2>/dev/null || true
        rm -rf config
    fi
}

echo "Cleaning up Home Assistant environment"
echo "==================="

echo "Removing config files from the HA app"
remove_config_files_for_ci

echo "Stopping all services (including ha-ssrf-listener)..."
docker compose down -v

echo "Removing any dangling containers..."
docker container prune -f

echo "Removing Docker images (keep base images to avoid re-pulling)..."
docker image rm -f home-assistant-android-ha-ssrf-listener || true

adb uninstall io.homeassistant.companion.android || true

APK_PATH="Home Assistant.apk"
if [ -f "$APK_PATH" ]; then
    echo "Removing downloaded APK: $APK_PATH"
    rm -f "$APK_PATH"
fi

if [ -f "scores.json" ]; then
    echo "Removing scores: scores.json"
    rm -f "scores.json"
fi

if [ -f "scores_remote_attacker.json" ]; then
    echo "Removing scores: scores_remote_attacker.json"
    rm -f "scores_remote_attacker.json"
fi

if [ -f "generic_scores.json" ]; then
    echo "Removing scores: generic_scores.json"
    rm -f "generic_scores.json"
fi

if [ -f "baseline_manifest.json" ]; then
    echo "Removing baseline: baseline_manifest.json"
    rm -f "baseline_manifest.json"
fi

echo "Removing log files recursively..."
find . -type f -name "*.log" -delete

echo "Cleanup complete!" 
echo "==================="