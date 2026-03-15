#!/bin/bash
#
# Build all synthetic-vuln APKs and the slim GKE runner Docker image.
#
# Usage (on a Linux VM with Docker):
#   bash infra/gke/build_and_push.sh [--push] [--image <name:tag>]       # slim (default)
#   bash infra/gke/build_and_push.sh --baked [--push] [--image <name:tag>]  # baked variant
#
# Default (slim):
#   1. Init git submodules for apps with synthetic vulnerabilities
#   2. Build clean + vulnerable APKs for each app/vuln pair
#   3. Build runner-slim image (with APKs baked in)
#   4. Optionally push to Docker Hub
#
# With --baked:
#   Same steps 1-2, but builds runner-baked image (~43-46GB) instead of
#   runner-slim. Includes emulator + agent Docker images pre-pulled inside
#   the image. Requires buildx with insecure entitlement (dockerd runs
#   during build).
#
# Prerequisites:
#   - Docker installed and running
#   - Git repo cloned with this script inside it

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

BASE_IMAGE="cybench/mobilecybench-orchestrator-slim:latest"
PUSH=false
BAKED=false
IMAGE_NAME=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --push) PUSH=true; shift ;;
        --image) IMAGE_NAME="$2"; shift 2 ;;
        --baked) BAKED=true; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# Set default image name based on variant
if [ -z "$IMAGE_NAME" ]; then
    if [ "$BAKED" = true ]; then
        IMAGE_NAME="cybench/mobilecybench-runner-baked:latest"
    else
        IMAGE_NAME="cybench/mobilecybench-runner:latest"
    fi
fi

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
SUBMODULE_PATHS=""
for app in "${!APP_VULNS[@]}"; do
    SUBMODULE_PATHS="$SUBMODULE_PATHS apps/$app/codebase"
done
echo "Initializing submodules: $SUBMODULE_PATHS"
git submodule update --init $SUBMODULE_PATHS

echo ""
echo "=== Step 2: Build APKs (inside orchestrator-slim container) ==="
docker pull "$BASE_IMAGE"

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
if [ "$BAKED" = true ]; then
    echo "=== Step 3: Build runner-baked image (with pre-pulled emulator + agent) ==="
    echo "This requires buildx with insecure entitlement for dockerd during build."

    # Create/reuse a builder with insecure entitlement
    BUILDER_NAME="mobilecybench-insecure"
    if ! docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
        echo "Creating buildx builder: $BUILDER_NAME"
        docker buildx create --name "$BUILDER_NAME" --use \
            --buildkitd-config <(printf '[worker.oci]\n  allowed-entitlements = ["security.insecure"]\n')
    else
        docker buildx use "$BUILDER_NAME"
    fi

    docker buildx build --builder "$BUILDER_NAME" --allow security.insecure \
        --load -f infra/gke/Dockerfile.runner-baked \
        --build-arg BASE_IMAGE="$BASE_IMAGE" \
        -t "$IMAGE_NAME" .
else
    echo "=== Step 3: Build runner-slim image ==="
    docker build -f infra/gke/Dockerfile.runner-slim \
        --build-arg BASE_IMAGE="$BASE_IMAGE" \
        -t "$IMAGE_NAME" .
fi

echo ""
echo "=== Build complete ==="
echo "Image: $IMAGE_NAME"

if [ "$PUSH" = true ]; then
    echo ""
    echo "=== Pushing to Docker Hub ==="
    docker push "$IMAGE_NAME"
    echo "Pushed: $IMAGE_NAME"
else
    echo ""
    echo "To push: docker push $IMAGE_NAME"
    echo "Or rerun with: bash infra/gke/build_and_push.sh --push"
fi
