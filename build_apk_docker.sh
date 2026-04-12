#!/bin/bash
# Build APKs inside the orchestrator Docker container.
# Wraps build_apk.sh with the container's pre-installed Java/Android SDK,
# avoiding host dependency issues.
#
# Usage: same as build_apk.sh, all args are passed through.
#   ./build_apk_docker.sh gotify
#   ./build_apk_docker.sh gotify --vuln vuln_1
#   ./build_apk_docker.sh conversations --hardened

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Image resolution: local > Docker Hub
DOCKERHUB_IMAGE="cybench/mobilecybench-orchestrator:latest"
LOCAL_IMAGE="mobilecybench-orchestrator:test"

if docker image inspect "$LOCAL_IMAGE" >/dev/null 2>&1; then
    IMAGE="$LOCAL_IMAGE"
elif docker image inspect "$DOCKERHUB_IMAGE" >/dev/null 2>&1; then
    IMAGE="$DOCKERHUB_IMAGE"
else
    echo "Pulling orchestrator image..."
    docker pull "$DOCKERHUB_IMAGE"
    IMAGE="$DOCKERHUB_IMAGE"
fi

echo "Using image: $IMAGE"
echo "Args: $*"
echo ""

# Extract app name (first non-flag arg) for submodule init
APP_NAME=""
for arg in "$@"; do
    [[ "$arg" == --* ]] && continue
    APP_NAME="$arg"
    break
done

if [ -z "$APP_NAME" ]; then
    echo "Error: no app name provided"
    echo "Usage: $0 <app_name> [build_apk.sh args...]"
    exit 1
fi

# Init submodule on host (needs git credentials, easier outside container)
git submodule update --init "apps/$APP_NAME/codebase" 2>/dev/null || true

docker run --rm \
    -v "$PROJECT_ROOT:/mobilecybench" \
    -v mobilecybench-gradle-cache:/root/.gradle \
    -w /mobilecybench \
    "$IMAGE" \
    bash -c './build_apk.sh "$@"' -- "$@"
