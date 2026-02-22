#!/bin/bash
# Local test for GKE infrastructure — validates container emulator mode
# inside the orchestrator, without GKE and without LLM calls.
#
# What this tests:
#   1. Orchestrator image builds
#   2. DinD starts inside orchestrator
#   3. Emulator launches as a Docker container (emulator_mode=container)
#   4. ADB connects to the emulator container
#   5. Emulator boots and app installs
#   6. Backend containers start (if app has them)
#   7. Kali container starts
#   8. dry_run interactive shell opens (no LLM)
#
# Prerequisites:
#   - Docker running on a Linux host with /dev/kvm
#   - Git submodules initialized for the test app
#
# Usage:
#   bash infra/gke/test_local.sh [APP_NAME]
#   bash infra/gke/test_local.sh moememos
#   bash infra/gke/test_local.sh moememos --native    # test native mode instead
#   bash infra/gke/test_local.sh moememos --skip-build # skip Docker image build

set -euo pipefail

APP_NAME="${1:-moememos}"
EMULATOR_MODE="container"
SKIP_BUILD=false

for arg in "$@"; do
    case "$arg" in
        --native) EMULATOR_MODE="native" ;;
        --skip-build) SKIP_BUILD=true ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
IMAGE_NAME="mobilecybench-orchestrator:test"

echo "=== MobileCyBench Local Infrastructure Test ==="
echo "App:            $APP_NAME"
echo "Emulator mode:  $EMULATOR_MODE"
echo "Project root:   $PROJECT_ROOT"
echo ""

# ─── Preflight: KVM check ─────────────────────────────────────────────────
if [ ! -e /dev/kvm ]; then
    echo "ERROR: /dev/kvm not found. The Android emulator requires KVM."
    echo "This test must run on a Linux host with hardware virtualization."
    exit 1
fi
echo "KVM: /dev/kvm found"

# ─── Step 1: Build orchestrator image ──────────────────────────────────────
if [ "$SKIP_BUILD" = true ]; then
    echo "--- Step 1: Skipping image build (--skip-build) ---"
    if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
        echo "ERROR: Image $IMAGE_NAME not found. Remove --skip-build to build it."
        exit 1
    fi
else
    echo "--- Step 1: Building orchestrator image (this takes ~15-20 min first time) ---"
    docker build -f "$PROJECT_ROOT/orchestrator/Dockerfile.orchestrator" \
        -t "$IMAGE_NAME" \
        "$PROJECT_ROOT"
fi
echo "Image ready: $IMAGE_NAME"
echo ""

# ─── Step 2: Determine build_type ─────────────────────────────────────────
CLEAN_APK="$PROJECT_ROOT/apps/$APP_NAME/apk/$APP_NAME.apk"
VULN_APK="$PROJECT_ROOT/apps/$APP_NAME/apk/vuln_0/$APP_NAME.apk"

if [ -f "$CLEAN_APK" ] && [ -f "$VULN_APK" ]; then
    BUILD_TYPE="skip-apk"
    echo "--- Step 2: Pre-built APKs found, using skip-apk mode ---"
else
    BUILD_TYPE="source"
    echo "--- Step 2: APKs not found, will build from source inside container ---"
    echo "  (This adds ~5-10 min. To skip next time, copy APKs to:"
    echo "    $CLEAN_APK"
    echo "    $VULN_APK"
    echo "  )"
fi
echo ""

# ─── Step 3: Create dry-run config ─────────────────────────────────────────
echo "--- Step 3: Creating test config ---"
cat > "$PROJECT_ROOT/runner_config_test.json" <<EOF
{
  "server_access": true,
  "build_type": "$BUILD_TYPE",
  "adb_access": "full",
  "max_iterations": 1,
  "max_model_response_tokens": 100,
  "model": "notarealmodel",
  "screenshot_mode": false,
  "headless_mode": false,
  "dry_run": true,
  "workflow": "exploit",
  "synthetic_vuln_id": "vuln_0",
  "agent_image": "cybench/mobilecybench:latest",
  "docker_mode": true,
  "emulator_mode": "$EMULATOR_MODE"
}
EOF
echo "Config written to runner_config_test.json"
echo ""

# ─── Step 4: Run orchestrator ──────────────────────────────────────────────
echo "--- Step 4: Running orchestrator (dry_run=true, no LLM) ---"
echo "The orchestrator will:"
echo "  - Start DinD"
echo "  - Start emulator ($EMULATOR_MODE mode)"
if [ "$BUILD_TYPE" = "source" ]; then
    echo "  - Build APKs from source"
fi
echo "  - Install app + backend"
echo "  - Start kali container"
echo "  - Open interactive shell (type 'exit' to finish)"
echo ""

docker run --rm \
    --privileged \
    --device /dev/kvm \
    --entrypoint bash \
    -v "$PROJECT_ROOT:/mobilecybench" \
    -v mobilecybench-docker-data:/var/lib/docker \
    -v mobilecybench-gradle-cache:/root/.gradle \
    -e APP_NAME="$APP_NAME" \
    -e DOCKER_TLS_CERTDIR= \
    "$IMAGE_NAME" \
    -c '
        set -e

        # Start DinD
        rm -f /var/run/docker.pid
        dockerd --host=unix:///var/run/docker.sock &
        timeout=30
        while [ $timeout -gt 0 ]; do
            docker info >/dev/null 2>&1 && break
            sleep 1
            timeout=$((timeout - 1))
        done
        if [ $timeout -eq 0 ]; then echo "Docker daemon failed to start"; exit 1; fi
        echo "Docker daemon ready"

        docker network create shared_net || true

        # Verify KVM inside container
        if [ -e /dev/kvm ]; then
            echo "KVM: /dev/kvm available inside container"
        else
            echo "ERROR: /dev/kvm not available inside container"
            exit 1
        fi

        # Install package
        cd /mobilecybench
        pip install --no-cache-dir -e . >/dev/null 2>&1 || true

        # Init submodule if needed
        git submodule update --init "apps/'"$APP_NAME"'/codebase" 2>/dev/null || true

        # Start ADB
        adb -a start-server

        echo ""
        echo "=========================================="
        echo "Infrastructure ready — running dry_run"
        echo "=========================================="
        echo ""

        python3 runner.py '"$APP_NAME"' --config runner_config_test.json
        EXIT_CODE=$?

        echo ""
        if [ $EXIT_CODE -eq 0 ]; then
            echo "=== TEST PASSED (exit code 0) ==="
        else
            echo "=== TEST FAILED (exit code $EXIT_CODE) ==="
        fi
        exit $EXIT_CODE
    '

# Cleanup
rm -f "$PROJECT_ROOT/runner_config_test.json"

echo ""
echo "=== Test complete ==="
