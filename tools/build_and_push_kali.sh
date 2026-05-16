#!/bin/bash

set -e

# WARNING: --push requires being logged into the cybench Docker Hub account
# Requires docker access token for cybench account
# 'docker login -u cybench'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

tag="v0.1.0"
arch="amd64,arm64"
mode=""

show_help() {
	echo "Usage: $0 <--local|--push|--pull> [--tag <tag>] [--arch <architecture>]"
	echo ""
	echo "Modes (exactly one required):"
	echo "  --local          Build the Docker image for the current architecture only (no push)"
	echo "  --push           Build multi-arch image with buildx and push to Docker Hub"
	echo "  --pull           Pull the image from Docker Hub"
	echo ""
	echo "Options:"
	echo "  --tag <tag>      Specify the image tag (default: latest)"
	echo "  --arch <arch>    Specify architectures for --push (default: amd64,arm64)"
	echo "  --help           Display this help message"
	exit 0
}

while [[ $# -gt 0 ]]; do
	case $1 in
	--local) mode="local" ;;
	--push) mode="push" ;;
	--pull) mode="pull" ;;
	--tag)
		tag="$2"
		shift
		[[ -z $tag ]] && {
			echo "Error: --tag requires a value"
			exit 1
		}
		;;
	--arch)
		arch="$2"
		shift
		[[ -z $arch ]] && {
			echo "Error: --arch requires a value"
			exit 1
		}
		;;
	--help) show_help ;;
	*)
		echo "Unknown parameter passed: $1"
		show_help
		;;
	esac
	shift
done

if [[ -z $mode ]]; then
	echo "Error: You must specify a mode (--local, --push, or --pull)"
	echo ""
	show_help
fi

image_name="cybench/mobilecybench-kali:${tag}"
dockerfile="${SCRIPT_DIR}/../agent/base/Dockerfile"
context="${SCRIPT_DIR}/../agent/base"

case $mode in
local)
	echo "Building locally for the current architecture..."
	docker build -f "${dockerfile}" -t "${image_name}" "${context}"
	echo "Done. Image: ${image_name}"
	;;
push)
	echo "Building multi-arch image (linux/${arch}) and pushing to Docker Hub..."

	# Ensure a buildx builder exists that supports multi-platform
	if ! docker buildx inspect mobilecybench-builder >/dev/null 2>&1; then
		echo "Creating buildx builder 'mobilecybench-builder'..."
		docker buildx create --name mobilecybench-builder --use
	else
		docker buildx use mobilecybench-builder
	fi

	# Build comma-separated arch list into --platform format
	platforms=""
	IFS=',' read -ra ARCH_ARRAY <<<"$arch"
	for a in "${ARCH_ARRAY[@]}"; do
		platforms="${platforms:+${platforms},}linux/${a}"
	done

	docker buildx build \
		-f "${dockerfile}" \
		--platform "${platforms}" \
		-t "${image_name}" \
		--push \
		"${context}"

	echo "Done. Pushed: ${image_name} (${platforms})"
	;;
pull)
	echo "Pulling ${image_name} from Docker Hub..."
	docker pull "${image_name}"
	echo "Done."
	;;
esac
