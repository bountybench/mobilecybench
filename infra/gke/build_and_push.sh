#!/bin/bash
#
# Build clean APKs for active apps and the GKE runner Docker image.
#
# Usage (on a Linux VM with Docker):
#   bash infra/gke/build_and_push.sh [--push] [--image <name:tag>] [--build-base]
#
# Steps:
#   1. Init git submodules for active apps from apps/app_catalog.json
#   2. Ensure orchestrator base image (pull from Docker Hub, or build locally with --build-base)
#   3. Build clean APKs for active apps
#   4. Build runner image (with APKs baked in)
#   5. Optionally push to Docker Hub (--push pushes both base and runner if --build-base)
#
# Prerequisites:
#   - Docker installed and running
#   - Git repo cloned with this script inside it

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

IMAGE_NAME="cybench/mobilecybench-runner:latest"
BASE_IMAGE="cybench/mobilecybench-orchestrator:latest"
PUSH=false
BUILD_BASE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --push) PUSH=true; shift ;;
        --image) IMAGE_NAME="$2"; shift 2 ;;
        --build-base) BUILD_BASE=true; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

ACTIVE_APPS=$(python3 -c 'import json; print("\n".join(json.load(open("apps/app_catalog.json"))["sets"]["in_scope"]))')
if [ -z "$ACTIVE_APPS" ]; then
    echo "ERROR: apps/app_catalog.json has no sets.in_scope apps"
    exit 1
fi

echo "Found active apps:"
for app in $ACTIVE_APPS; do
    if [ ! -d "apps/$app" ]; then
        echo "ERROR: active catalog app missing under apps/: $app"
        exit 1
    fi
    echo "  $app"
done

echo "=== Step 1: Initialize git submodules ==="
# Discover every submodule declared under apps/<active_app>/ in .gitmodules.
# Apps can declare auxiliary submodules beyond `codebase` (e.g. jitsi-meet needs
# apps/jitsi-meet/jitsi-docker for its runtime), so we enumerate from .gitmodules
# rather than hardcoding `codebase` — any submodule an app ships will be initialized.
SUBMODULE_PATHS=""
ALL_SUBMODULE_PATHS=$(git config --file .gitmodules --get-regexp 'submodule\..*\.path' 2>/dev/null | awk '{print $2}' || true)
for app in $ACTIVE_APPS; do
    for path in $ALL_SUBMODULE_PATHS; do
        case "$path" in
            apps/$app/*) SUBMODULE_PATHS="$SUBMODULE_PATHS $path" ;;
        esac
    done
done
if [ -n "$SUBMODULE_PATHS" ]; then
    echo "Initializing submodules:$SUBMODULE_PATHS"
    git submodule update --init $SUBMODULE_PATHS
else
    echo "No active app submodules found."
fi

echo ""
echo "=== Step 2: Ensure orchestrator base image ==="
if [ "$BUILD_BASE" = true ]; then
    echo "Building base image from orchestrator/Dockerfile.orchestrator ..."
    docker build -f orchestrator/Dockerfile.orchestrator -t "$BASE_IMAGE" .
    if [ "$PUSH" = true ]; then
        echo "Pushing base image: $BASE_IMAGE"
        docker push "$BASE_IMAGE"
    fi
else
    echo "Pulling base image from Docker Hub ..."
    docker pull "$BASE_IMAGE"
fi

echo ""
echo "=== Step 3: Build APKs (inside orchestrator container) ==="

# Build a list of build commands for all apps
BUILD_CMDS=""
for app in $ACTIVE_APPS; do
    if [ -f "apps/$app/apk/$app.apk" ]; then
        echo "[$app] Clean APK already exists, skipping"
    else
        BUILD_CMDS="$BUILD_CMDS
echo '=== Building $app (clean) ===' && ./build_apk.sh $app || echo 'FAILED:$app:clean'"
    fi
done

if [ -n "$BUILD_CMDS" ]; then
    echo "Running APK builds inside container..."
    docker run --rm \
        --entrypoint bash \
        -v "$ROOT_DIR:/mobilecybench" \
        -v mobilecybench-gradle-cache:/root/.gradle \
        -w /mobilecybench \
        "$BASE_IMAGE" \
        -c "git config --global --add safe.directory /mobilecybench && $BUILD_CMDS"
else
    echo "All APKs already exist, skipping builds."
fi

echo ""
echo "=== APK Build Summary ==="
for app in $ACTIVE_APPS; do
    clean="missing"
    [ -f "apps/$app/apk/$app.apk" ] && clean="ok"
    echo "  $app: clean=$clean"
done

echo ""
echo "=== Step 4: Build runner image ==="
docker build -f infra/gke/Dockerfile.runner \
    --build-arg BASE_IMAGE="$BASE_IMAGE" \
    -t "$IMAGE_NAME" .

echo ""
echo "=== Build complete ==="
echo "Image: $IMAGE_NAME"

if [ "$PUSH" = true ]; then
    echo ""
    echo "=== Step 5: Pushing runner to Docker Hub ==="
    docker push "$IMAGE_NAME"
    echo "Push complete: $IMAGE_NAME"
else
    echo ""
    echo "To push: docker push $IMAGE_NAME"
    echo "Or rerun with: bash infra/gke/build_and_push.sh --push"
fi
