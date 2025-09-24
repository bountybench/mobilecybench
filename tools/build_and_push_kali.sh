#!/bin/bash

set -e

# WARNING: This script requires being logged into the cybench Docker Hub account
# Requires docker access token for cybench account
# 'docker login -u cybench' 

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

tag="latest"
build_locally=0
arch="amd64,arm64"

show_help() {
	echo "Usage: $0 [--local] [--tag <tag>] [--arch <architecture>]"
	echo ""
	echo "  --local          Build the Docker image locally"
	echo "  --tag <tag>      Specify the tag for the Docker image (default: latest)"
	echo "  --arch <architecture> Specify the architecture for the Docker image (default: amd64,arm64)"
	echo "  --help           Display this help message"
	exit 0
}

while [[ $# -gt 0 ]]; do
	case $1 in
	--local) build_locally=1 ;;
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

image_name="cybench/mobilecybench:${tag}"

if [[ ${build_locally} -eq 1 ]]; then
	echo "Building locally for the current architecture..."
	docker build -f "${SCRIPT_DIR}/../agent/kali/Dockerfile.kali" -t "${image_name}" "${SCRIPT_DIR}/../" "$@"
else
	echo "Pulling Docker image from Docker Hub..."
	docker pull "${image_name}" || {
		echo "Remote image not found, building locally with buildx for ${arch}..."
		docker buildx build -f "${SCRIPT_DIR}/../agent/kali/Dockerfile.kali" --platform "linux/${arch}" -t "${image_name}" --push "${SCRIPT_DIR}/../" "$@"
	}
fi
