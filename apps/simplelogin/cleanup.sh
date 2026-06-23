#!/bin/bash
set -e

# Always operate on this app's fixture dir, regardless of caller's cwd.
# Otherwise `docker compose down -v` and the `rm -f` lines silently no-op
# when invoked from repo root, leaving docker volumes (and the
# baseline_manifest.json captured from a compromised DB) behind. That
# pattern was the root cause of poisoned-baseline carryover between runs.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Cleaning up SimpleLogin environment"
echo "==================="

DC="docker compose"

echo "Stopping all services..."
$DC down -v 2>/dev/null || true

echo "Removing any dangling containers..."
docker container prune -f 2>/dev/null || true

echo "Removing test result files and probe baselines..."
rm -f *_results.json scores.json generic_scores.json scores_remote_attacker.json baseline_manifest.json 2>/dev/null || true

echo "Removing pipeline-generated baselines and manifests..."
rm -f baseline_apk_sha256.txt baseline_clipboard.txt baseline_glide_cache.txt baseline_system_cacerts.txt 2>/dev/null || true
rm -f device_epoch_baseline.txt 2>/dev/null || true
rm -f last_state.json last_state_seeding.json 2>/dev/null || true
rm -f prepare_victim_run.log 2>/dev/null || true
rm -f security_breach.log 2>/dev/null || true
rm -f vuln_scenarios/*/fake_agent_log.log 2>/dev/null || true

echo "Removing log files..."
find . -type f -name "*.log" -delete 2>/dev/null || true

echo "Removing python caches..."
find . -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true

echo "Cleanup complete!"
echo "==================="
