#!/bin/bash
#
# Build all synthetic-vuln APKs and the GKE runner Docker image.
#
# Usage (on a Linux VM with Docker):
#   bash infra/gke/build_and_push.sh [--push] [--image <name:tag>] [--build-base]
#
# Steps:
#   1. Init git submodules for apps with synthetic vulnerabilities
#   2. Ensure orchestrator base image (pull from Docker Hub, or build locally with --build-base)
#   3. Build clean + vulnerable APKs for each app/vuln pair
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

# Discover apps with synthetic vulnerabilities and their vuln IDs
declare -A APP_VULNS=()
for sv_dir in apps/*/synthetic_vulnerabilities; do
    [ -d "$sv_dir" ] || continue
    app="$(basename "$(dirname "$sv_dir")")"
    vulns=""
    for vuln_dir in "$sv_dir"/vuln_*; do
        [ -d "$vuln_dir" ] || continue
        vulns="$vulns $(basename "$vuln_dir")"
    done
    vulns="${vulns# }"  # trim leading space
    if [ -n "$vulns" ]; then
        APP_VULNS[$app]="$vulns"
    fi
done

if [ ${#APP_VULNS[@]} -eq 0 ]; then
    echo "ERROR: No apps with synthetic vulnerabilities found"
    exit 1
fi

echo "Found ${#APP_VULNS[@]} apps with synthetic vulnerabilities:"
for app in $(echo "${!APP_VULNS[@]}" | tr ' ' '\n' | sort); do
    echo "  $app: ${APP_VULNS[$app]}"
done

echo "=== Step 1: Initialize git submodules ==="
# Discover every submodule declared under apps/<app_with_vulns>/ in .gitmodules.
# Apps can declare auxiliary submodules beyond `codebase` (e.g. jitsi-meet needs
# apps/jitsi-meet/jitsi-docker for its runtime), so we enumerate from .gitmodules
# rather than hardcoding `codebase` — any submodule an app ships will be initialized.
SUBMODULE_PATHS=""
ALL_SUBMODULE_PATHS=$(git config --file .gitmodules --get-regexp 'submodule\..*\.path' | awk '{print $2}')
for app in "${!APP_VULNS[@]}"; do
    for path in $ALL_SUBMODULE_PATHS; do
        case "$path" in
            apps/$app/*) SUBMODULE_PATHS="$SUBMODULE_PATHS $path" ;;
        esac
    done
done
echo "Initializing submodules:$SUBMODULE_PATHS"
git submodule update --init $SUBMODULE_PATHS

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
FAILED_BUILDS=()
for app in $(echo "${!APP_VULNS[@]}" | tr ' ' '\n' | sort); do
    vulns="${APP_VULNS[$app]}"

    # Clean APK
    if [ -f "apps/$app/apk/$app.apk" ]; then
        echo "[$app] Clean APK already exists, skipping"
    else
        BUILD_CMDS="$BUILD_CMDS
echo '=== Building $app (clean) ===' && ./build_apk.sh $app || echo 'FAILED:$app:clean'"
    fi

    # Vulnerable APKs
    for vuln_id in $vulns; do
        if [ -f "apps/$app/apk/$vuln_id/$app.apk" ]; then
            echo "[$app] Vulnerable APK ($vuln_id) already exists, skipping"
        else
            BUILD_CMDS="$BUILD_CMDS
echo '=== Building $app ($vuln_id) ===' && ./build_apk.sh $app --vuln $vuln_id || echo 'FAILED:$app:$vuln_id'"
        fi
    done
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
for app in $(echo "${!APP_VULNS[@]}" | tr ' ' '\n' | sort); do
    vulns="${APP_VULNS[$app]}"
    clean="missing"
    [ -f "apps/$app/apk/$app.apk" ] && clean="ok"
    vuln_status=""
    for vuln_id in $vulns; do
        s="missing"
        [ -f "apps/$app/apk/$vuln_id/$app.apk" ] && s="ok"
        vuln_status="$vuln_status $vuln_id=$s"
    done
    echo "  $app: clean=$clean$vuln_status"
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
