#!/bin/bash
# Local test for GKE infrastructure — validates emulator modes
# inside the orchestrator, without GKE and without LLM calls.
#
# What this tests:
#   1. Orchestrator image builds/pulls
#   2. DinD starts inside orchestrator
#   3. Emulator launches (native or container mode)
#   4. ADB connects to the emulator
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
#   bash infra/gke/test_local.sh moememos --container   # emulator in separate container
#   bash infra/gke/test_local.sh moememos --skip-build   # never build, only use existing/pull
#   bash infra/gke/test_local.sh moememos --gold-run     # run reference exploits

set -euo pipefail

APP_NAME="moememos"
EMULATOR_BACKEND="native"
SKIP_BUILD=false
DRY_RUN=true
GOLD_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --native) EMULATOR_BACKEND="native"; shift ;;
        --container) EMULATOR_BACKEND="container"; shift ;;
        --skip-build) SKIP_BUILD=true; shift ;;
        --dry-run) DRY_RUN=true; GOLD_RUN=false; shift ;;
        --gold-run) GOLD_RUN=true; DRY_RUN=false; shift ;;
        --no-dry-run) DRY_RUN=false; shift ;;
        --*) echo "Unknown arg: $1"; exit 1 ;;
        *) APP_NAME="$1"; shift ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Docker Hub image names
DOCKERHUB_ORCHESTRATOR="cybench/mobilecybench-orchestrator:latest"
DOCKERHUB_ORCHESTRATOR_SLIM="cybench/mobilecybench-orchestrator-slim:latest"
DOCKERHUB_EMULATOR="cybench/mobilecybench-emulator:latest"

echo "=== MobileCyBench Local Infrastructure Test ==="
echo "App:            $APP_NAME"
echo "Emulator backend: $EMULATOR_BACKEND"
echo "Dry run:        $DRY_RUN"
echo "Gold run:       $GOLD_RUN"
echo "Project root:   $PROJECT_ROOT"
echo ""

# ─── Preflight: KVM check ─────────────────────────────────────────────────
if [ ! -e /dev/kvm ]; then
    echo "ERROR: /dev/kvm not found. The Android emulator requires KVM."
    echo "This test must run on a Linux host with hardware virtualization."
    exit 1
fi
echo "KVM: /dev/kvm found"

# ─── Helper: ensure an image is available ─────────────────────────────────
# Priority: 1) local  2) Docker Hub  3) build from Dockerfile
# --skip-build disables step 3.
ensure_image() {
    local local_name="$1"
    local hub_name="$2"
    local dockerfile="$3"
    local result_var="$4"   # variable name to store the resolved image name

    # 1. Check locally
    if docker image inspect "$local_name" >/dev/null 2>&1; then
        echo "  Found locally: $local_name"
        eval "$result_var='$local_name'"
        return 0
    fi
    if [ "$local_name" != "$hub_name" ] && docker image inspect "$hub_name" >/dev/null 2>&1; then
        echo "  Found locally: $hub_name"
        eval "$result_var='$hub_name'"
        return 0
    fi

    # 2. Try pulling from Docker Hub
    echo "  Not found locally, pulling $hub_name ..."
    if docker pull "$hub_name" 2>/dev/null; then
        echo "  Pulled: $hub_name"
        eval "$result_var='$hub_name'"
        return 0
    fi
    echo "  Pull failed (image may not exist on Docker Hub yet)"

    # 3. Build from Dockerfile
    if [ "$SKIP_BUILD" = true ]; then
        echo "  ERROR: --skip-build set and image not available."
        return 1
    fi
    if [ -z "$dockerfile" ]; then
        echo "  ERROR: No Dockerfile specified for building."
        return 1
    fi
    echo "  Building from $dockerfile ..."
    docker build -f "$PROJECT_ROOT/$dockerfile" -t "$local_name" "$PROJECT_ROOT"
    eval "$result_var='$local_name'"
    return 0
}

# ─── Step 1: Ensure orchestrator image ────────────────────────────────────
echo "--- Step 1: Ensuring orchestrator image ---"
if [ "$EMULATOR_BACKEND" = "container" ]; then
    ensure_image "mobilecybench-orchestrator-slim:test" \
                 "$DOCKERHUB_ORCHESTRATOR_SLIM" \
                 "orchestrator/Dockerfile.orchestrator-slim" \
                 IMAGE_NAME
else
    ensure_image "mobilecybench-orchestrator:test" \
                 "$DOCKERHUB_ORCHESTRATOR" \
                 "orchestrator/Dockerfile.orchestrator" \
                 IMAGE_NAME
fi
echo "Orchestrator image: $IMAGE_NAME"
echo ""

# ─── Step 1b: Resolve emulator image name (container mode only) ──────────
# The emulator image runs inside DinD, not on the host. We only need to
# determine the image name here. DinD will pull from Docker Hub or load
# from a tar (if built locally) in Step 4.
EMULATOR_IMAGE_NAME=""
if [ "$EMULATOR_BACKEND" = "container" ]; then
    echo "--- Step 1b: Resolving emulator image ---"
    # Check if a local build exists on the host (for save/load into DinD)
    if docker image inspect "mobilecybench-emulator:test" >/dev/null 2>&1; then
        EMULATOR_IMAGE_NAME="mobilecybench-emulator:test"
        echo "  Found local emulator image: $EMULATOR_IMAGE_NAME (will save/load into DinD)"
    else
        # Default to Docker Hub — DinD will pull it directly
        EMULATOR_IMAGE_NAME="$DOCKERHUB_EMULATOR"
        echo "  No local emulator image — DinD will pull $EMULATOR_IMAGE_NAME"
        if [ "$SKIP_BUILD" != true ]; then
            # Offer to build locally if user hasn't pushed to Docker Hub yet
            echo "  (To build locally instead: docker build -f orchestrator/Dockerfile.emulator -t mobilecybench-emulator:test .)"
        fi
    fi
    echo ""
fi

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
trap 'rm -f "$PROJECT_ROOT/runner_config_test.json"' EXIT

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
  "dry_run": $DRY_RUN,
  "gold_run": $GOLD_RUN,
  "workflow": "exploit",
  "synthetic_vuln_id": "vuln_0",
  "agent_image": "cybench/mobilecybench:latest",
  "emulator_display": "headless",
  "emulator_backend": "$EMULATOR_BACKEND"
}
EOF
echo "Config written to runner_config_test.json"
echo ""

# ─── Step 4: Run orchestrator ──────────────────────────────────────────────
echo "--- Step 4: Running orchestrator (dry_run=$DRY_RUN, gold_run=$GOLD_RUN) ---"
echo "The orchestrator will:"
echo "  - Start DinD"
echo "  - Start emulator ($EMULATOR_BACKEND mode)"
if [ "$BUILD_TYPE" = "source" ]; then
    echo "  - Build APKs from source"
fi
echo "  - Install app + backend"
echo "  - Start kali container"
echo "  - Open interactive shell (type 'exit' to finish)"
echo ""

# For container mode: get emulator image into DinD.
# If the image is on Docker Hub, inner DinD pulls directly.
# If local-only, save as tar and mount into the container.
EMULATOR_IMAGE_TAR=""
if [ "$EMULATOR_BACKEND" = "container" ]; then
    if [[ "$EMULATOR_IMAGE_NAME" == cybench/* ]]; then
        # Docker Hub image — inner DinD will pull it directly
        echo "Emulator image on Docker Hub — DinD will pull inside container"
    else
        # Local image — save/load into DinD
        echo "Saving local emulator image for DinD..."
        EMULATOR_IMAGE_TAR="/tmp/mobilecybench-emulator-image.tar"
        docker save "$EMULATOR_IMAGE_NAME" -o "$EMULATOR_IMAGE_TAR"
        echo "Image saved ($(du -h "$EMULATOR_IMAGE_TAR" | cut -f1))"
    fi
fi

docker run --rm \
    --privileged \
    --device /dev/kvm \
    --entrypoint bash \
    -v "$PROJECT_ROOT:/mobilecybench" \
    -v mobilecybench-docker-data:/var/lib/docker \
    -v mobilecybench-gradle-cache:/root/.gradle \
    ${EMULATOR_IMAGE_TAR:+-v "$EMULATOR_IMAGE_TAR:/tmp/emulator-image.tar"} \
    -e APP_NAME="$APP_NAME" \
    -e EMULATOR_IMAGE="${EMULATOR_IMAGE_NAME}" \
    -e DOCKER_TLS_CERTDIR= \
    -e DOCKERHUB_USERNAME="${DOCKERHUB_USERNAME:-}" \
    -e DOCKERHUB_TOKEN="${DOCKERHUB_TOKEN:-}" \
    "$IMAGE_NAME" \
    -c '
        set -e

        # Start DinD
        rm -f /var/run/docker.pid
        # Use explicit DNS to avoid emulator's 10.0.2.3 polluting DinD resolver
        dockerd --host=unix:///var/run/docker.sock --dns 8.8.8.8 --dns 8.8.4.4 &
        timeout=30
        while [ $timeout -gt 0 ]; do
            docker info >/dev/null 2>&1 && break
            sleep 1
            timeout=$((timeout - 1))
        done
        if [ $timeout -eq 0 ]; then echo "Docker daemon failed to start"; exit 1; fi
        echo "Docker daemon ready"

        # Docker Hub auth (optional — avoids rate limits on image pulls)
        if [ -n "${DOCKERHUB_USERNAME:-}" ] && [ -n "${DOCKERHUB_TOKEN:-}" ]; then
            echo "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin
            echo "Docker Hub login successful"
        fi

        docker network create shared_net || true

        # Get emulator image into DinD (container mode only)
        if [ -f /tmp/emulator-image.tar ]; then
            echo "Loading emulator image into DinD from tar..."
            docker load -i /tmp/emulator-image.tar
        elif [ -n "${EMULATOR_IMAGE:-}" ]; then
            echo "Checking if emulator image exists in DinD..."
            if ! docker image inspect "$EMULATOR_IMAGE" >/dev/null 2>&1; then
                echo "Pulling emulator image into DinD: $EMULATOR_IMAGE"
                docker pull "$EMULATOR_IMAGE"
            else
                echo "Emulator image already cached in DinD"
            fi
        fi
        echo "DinD images:"
        docker images

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

# Clean up saved image tar
if [ -n "$EMULATOR_IMAGE_TAR" ] && [ -f "$EMULATOR_IMAGE_TAR" ]; then
    rm -f "$EMULATOR_IMAGE_TAR"
fi

echo ""
echo "=== Test complete ==="
