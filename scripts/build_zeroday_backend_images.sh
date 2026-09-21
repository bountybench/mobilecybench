#!/usr/bin/env bash
# Build the vulnerable + patched backend images for a *server-side* zero-day task.
#
# A server-side task's fix.patch targets the backend server (e.g. wallabag PHP,
# home-assistant-core Python), not the Android app. The runner swaps the backend
# image per phase (see evaluation/backend_image_swap.py); this script produces
# the two images that swap refers to, from the bundle's own fix.patch.
#
# Usage:
#   scripts/build_zeroday_backend_images.sh <app> <report> [--push]
#     e.g. scripts/build_zeroday_backend_images.sh wallabag report-2
#
# Reads zerodays/reports/<app>/<report>/task/metadata.json .server_side:
#   .service                     compose service (informational here)
#   .images.vulnerable/.secure   tags to produce
#   .build.base_image            upstream image the baseline is FROM
#   .build.context               optional bundle-relative dir with a Dockerfile
#                                that adds the app's harness tweaks (entrypoint,
#                                tools) on top of base_image
#   .build.patch_workdir         in-image dir the backend source lives under
#   .build.patch_strip           git-apply -p<N> strip (default 1)
#
# DRAFT: the git-apply-in-image step assumes the base image ships `git` (or the
# build.context layer installs it). Validate per app on a Docker host before
# wiring into CI.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PYTHON_BIN:-python3}"

app="${1:?usage: build_zeroday_backend_images.sh <app> <report> [--push]}"
report="${2:?usage: build_zeroday_backend_images.sh <app> <report> [--push]}"
push="${3:-}"

task_dir="$PROJECT_ROOT/zerodays/reports/$app/$report/task"
meta="$task_dir/metadata.json"
patch_file="$task_dir/fix.patch"
[ -f "$meta" ] || { echo "metadata.json not found: $meta" >&2; exit 1; }
[ -f "$patch_file" ] || { echo "fix.patch not found: $patch_file" >&2; exit 1; }

read_field() { "$PY" -c 'import json,sys; d=json.load(open(sys.argv[1])).get("server_side") or {}; \
ks=sys.argv[2].split("."); v=d
for k in ks: v=(v or {}).get(k) if isinstance(v,dict) else None
print("" if v is None else v)' "$meta" "$1"; }

service="$(read_field service)"
img_vuln="$(read_field images.vulnerable)"
img_secure="$(read_field images.secure)"
base_image="$(read_field build.base_image)"
context_rel="$(read_field build.context)"
patch_workdir="$(read_field build.patch_workdir)"
patch_strip="$(read_field build.patch_strip)"; patch_strip="${patch_strip:-1}"

[ -n "$service" ] && [ -n "$img_vuln" ] && [ -n "$img_secure" ] || {
  echo "metadata.server_side must set service + images.{vulnerable,secure}" >&2; exit 1; }
[ -n "$base_image" ] && [ -n "$patch_workdir" ] || {
  echo "metadata.server_side.build must set base_image + patch_workdir" >&2; exit 1; }

echo "== server-side backend images for $app/$report =="
echo "   service=$service base=$base_image workdir=$patch_workdir strip=$patch_strip"
echo "   vulnerable -> $img_vuln"
echo "   secure     -> $img_secure"

build_ctx="$(mktemp -d)"
trap 'rm -rf "$build_ctx"' EXIT
cp "$patch_file" "$build_ctx/fix.patch"

# ---- vulnerable image ----------------------------------------------------
# If the bundle ships a context Dockerfile (harness tweaks: entrypoint, tools),
# build FROM base_image through it; else tag base_image directly.
if [ -n "$context_rel" ] && [ -f "$task_dir/../$context_rel/Dockerfile" ]; then
  echo "-- building vulnerable image via bundle context $context_rel"
  docker build --build-arg BASE_IMAGE="$base_image" \
    -t "$img_vuln" "$task_dir/../$context_rel"
else
  echo "-- tagging base image as vulnerable (no context Dockerfile)"
  docker pull "$base_image"
  docker tag "$base_image" "$img_vuln"
fi

# ---- patched image -------------------------------------------------------
# FROM the vulnerable image so any harness tweaks carry, then apply fix.patch
# into the backend source dir. git apply works outside a git repo.
cat > "$build_ctx/Dockerfile.patched" <<EOF
FROM $img_vuln
COPY fix.patch /tmp/mcb-fix.patch
RUN cd "$patch_workdir" && git apply -p$patch_strip /tmp/mcb-fix.patch && rm -f /tmp/mcb-fix.patch
EOF
echo "-- building patched image (git apply -p$patch_strip in $patch_workdir)"
docker build -f "$build_ctx/Dockerfile.patched" -t "$img_secure" "$build_ctx"

echo "== built:"
docker image ls --format '   {{.Repository}}:{{.Tag}}  {{.ID}}  {{.Size}}' \
  | grep -E "$(printf '%s|%s' "${img_vuln%%:*}" "${img_secure%%:*}")" || true

if [ "$push" = "--push" ]; then
  echo "-- pushing images"
  docker push "$img_vuln"
  docker push "$img_secure"
fi
echo "done. Pin the pushed digests into metadata.server_side.images for reproducibility."
