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
#   runner-slim. Runs a temporary dockerd on the host to pull emulator +
#   agent images, then COPY the Docker data directory into the image.
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
    echo "=== Step 3: Prepare baked Docker data ==="
    EMULATOR_IMAGE="${EMULATOR_IMAGE:-cybench/mobilecybench-emulator:latest}"
    AGENT_IMAGE="${AGENT_IMAGE:-cybench/mobilecybench:latest}"
    BAKED_DIR="$ROOT_DIR/.docker-baked"

    if [ -d "$BAKED_DIR" ] && [ "$(ls -A "$BAKED_DIR" 2>/dev/null)" ]; then
        echo "Baked Docker data already exists at $BAKED_DIR, reusing."
        echo "  (Delete .docker-baked/ to force re-pull)"
    else
        rm -rf "$BAKED_DIR"
        mkdir -p "$BAKED_DIR"

        echo "Starting temporary dockerd to pull images..."
        dockerd --data-root "$BAKED_DIR" --host=unix:///tmp/baked-docker.sock \
            --pidfile=/tmp/baked-dockerd.pid &>/tmp/baked-dockerd.log &
        DOCKERD_PID=$!
        trap 'kill $DOCKERD_PID 2>/dev/null; wait $DOCKERD_PID 2>/dev/null; rm -f /tmp/baked-docker.sock /tmp/baked-dockerd.pid' EXIT

        for i in $(seq 1 60); do
            docker -H unix:///tmp/baked-docker.sock info >/dev/null 2>&1 && break
            sleep 1
        done
        if ! docker -H unix:///tmp/baked-docker.sock info >/dev/null 2>&1; then
            echo "ERROR: temporary dockerd failed to start"
            cat /tmp/baked-dockerd.log
            exit 1
        fi
        echo "Temporary dockerd ready"

        echo "Pulling $EMULATOR_IMAGE..."
        docker -H unix:///tmp/baked-docker.sock pull "$EMULATOR_IMAGE"
        echo "Pulling $AGENT_IMAGE..."
        docker -H unix:///tmp/baked-docker.sock pull "$AGENT_IMAGE"

        echo "Images pulled:"
        docker -H unix:///tmp/baked-docker.sock images

        # Stop temporary dockerd
        kill "$DOCKERD_PID" && wait "$DOCKERD_PID" 2>/dev/null || true
        rm -f /tmp/baked-docker.sock /tmp/baked-dockerd.pid
        trap - EXIT

        echo "Docker data directory ready ($(du -sh "$BAKED_DIR" | cut -f1))"
    fi

    # Tar the Docker data directory — COPY in Dockerfile can't handle device
    # nodes in overlay2, so we ship a tar and extract at runtime.
    BAKED_TAR="$ROOT_DIR/.docker-baked.tar"
    if [ ! -f "$BAKED_TAR" ] || [ "$BAKED_DIR" -nt "$BAKED_TAR" ]; then
        echo "Creating .docker-baked.tar..."
        tar -C "$BAKED_DIR" -cf "$BAKED_TAR" .
        echo "Tar ready ($(du -sh "$BAKED_TAR" | cut -f1))"
    else
        echo "Reusing existing .docker-baked.tar ($(du -sh "$BAKED_TAR" | cut -f1))"
    fi

    echo ""
    echo "=== Step 4: Build runner-baked image ==="
    docker build -f infra/gke/Dockerfile.runner-baked \
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
