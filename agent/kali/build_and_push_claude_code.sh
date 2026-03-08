#!/usr/bin/env bash
set -euo pipefail

LOCAL_TAG="mobilecybench-claude-code:local"
REMOTE_TAG="cybench/mobilecybench:claudecode"

echo "Building ${LOCAL_TAG}..."
docker build -t "$LOCAL_TAG" -f "$(dirname "$0")/Dockerfile.claude-code" "$(dirname "$0")/../.."

echo "Tagging as ${REMOTE_TAG}..."
docker tag "$LOCAL_TAG" "$REMOTE_TAG"

echo "Pushing ${REMOTE_TAG}..."
docker push "$REMOTE_TAG"

echo "Done: ${REMOTE_TAG}"
