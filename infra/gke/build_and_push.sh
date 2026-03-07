#!/bin/bash
#
# Build all synthetic-vuln APKs and the slim GKE runner Docker image.
#
# Usage (on a Linux VM with Docker):
#   bash infra/gke/build_and_push.sh [--push] [--image <name:tag>]
#
# Steps:
#   1. Init git submodules for apps with synthetic vulnerabilities
#   2. Build clean + vulnerable APKs for each app/vuln pair
#   3. Build orchestrator-slim base image
#   4. Build runner-slim image (with APKs baked in)
#   5. Optionally push to Docker Hub
#
# Prerequisites:
#   - Docker installed and running
#   - Git repo cloned with this script inside it

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

IMAGE_NAME="cybench/mobilecybench-runner:latest"
BASE_IMAGE="cybench/mobilecybench-orchestrator-slim:latest"
PUSH=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --push) PUSH=true; shift ;;
        --image) IMAGE_NAME="$2"; shift 2 ;;
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
SUBMODULE_PATHS=""
for app in "${!APP_VULNS[@]}"; do
    SUBMODULE_PATHS="$SUBMODULE_PATHS apps/$app/codebase"
done
echo "Initializing submodules: $SUBMODULE_PATHS"
git submodule update --init $SUBMODULE_PATHS

echo ""
echo "=== Step 2: Build APKs ==="
FAILED_BUILDS=()
for app in $(echo "${!APP_VULNS[@]}" | tr ' ' '\n' | sort); do
    vulns="${APP_VULNS[$app]}"

    # Build clean APK
    if [ -f "apps/$app/apk/$app.apk" ]; then
        echo "[$app] Clean APK already exists, skipping"
    else
        echo "[$app] Building clean APK..."
        if ./build_apk.sh "$app"; then
            echo "[$app] Clean APK built successfully"
        else
            echo "[$app] ERROR: Clean APK build failed"
            FAILED_BUILDS+=("$app:clean")
            continue
        fi
    fi

    # Build vulnerable APKs
    for vuln_id in $vulns; do
        if [ -f "apps/$app/apk/$vuln_id/$app.apk" ]; then
            echo "[$app] Vulnerable APK ($vuln_id) already exists, skipping"
        else
            echo "[$app] Building vulnerable APK ($vuln_id)..."
            if ./build_apk.sh "$app" --vuln "$vuln_id"; then
                echo "[$app] Vulnerable APK ($vuln_id) built successfully"
            else
                echo "[$app] ERROR: Vulnerable APK ($vuln_id) build failed"
                FAILED_BUILDS+=("$app:$vuln_id")
            fi
        fi
    done
done

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

if [ ${#FAILED_BUILDS[@]} -gt 0 ]; then
    echo ""
    echo "WARNING: ${#FAILED_BUILDS[@]} build(s) failed: ${FAILED_BUILDS[*]}"
    echo "Continuing with Docker build anyway (failed apps won't have APKs baked in)."
fi

echo ""
echo "=== Step 3: Pull orchestrator-slim base image ==="
docker pull "$BASE_IMAGE"

echo ""
echo "=== Step 4: Build runner-slim image ==="
docker build -f infra/gke/Dockerfile.runner-slim \
    --build-arg BASE_IMAGE="$BASE_IMAGE" \
    -t "$IMAGE_NAME" .

echo ""
echo "=== Build complete ==="
echo "Image: $IMAGE_NAME"

if [ "$PUSH" = true ]; then
    echo ""
    echo "=== Step 5: Pushing to Docker Hub ==="
    docker push "$IMAGE_NAME"
    echo "Push complete: $IMAGE_NAME"
else
    echo ""
    echo "To push: docker push $IMAGE_NAME"
    echo "Or rerun with: bash infra/gke/build_and_push.sh --push"
fi
