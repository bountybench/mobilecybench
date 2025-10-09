#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "======================================="
echo "MobileCybench Orchestrator Build Script"
echo "======================================="

# Parse command line arguments
NO_CACHE=false
PLATFORM=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --no-cache)
            NO_CACHE=true
            shift
            ;;
        --platform)
            PLATFORM="$2"
            shift 2
            ;;
        --platform=*)
            PLATFORM="${1#*=}"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --no-cache        Build without using Docker cache"
            echo "  --platform PLATFORM   Build for specific platform (linux/amd64, linux/arm64)"
            echo "  -h, --help        Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                    # Build using cache for current platform"
            echo "  $0 --no-cache         # Force rebuild without cache"
            echo "  $0 --platform linux/amd64  # Build for x86_64 architecture"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use -h or --help for usage information"
            exit 1
            ;;
    esac
done

# Change to project root
cd "$PROJECT_ROOT"

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed"
    echo "Please install Docker from https://www.docker.com/"
    exit 1
fi

# Check if Docker daemon is running
if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker daemon is not running"
    echo "Please start Docker and try again"
    exit 1
fi

# Always use linux/amd64 platform by default
if [ -z "$PLATFORM" ]; then
    PLATFORM="linux/amd64"
    ARCH=$(uname -m)
    if [ "$ARCH" = "arm64" ] || [ "$ARCH" = "aarch64" ]; then
        echo "Note: ARM64 system detected, but building for linux/amd64 for compatibility."
    fi
fi

echo "Building for platform: $PLATFORM"

# Build arguments
BUILD_ARGS="--platform $PLATFORM"
BUILD_ARGS="$BUILD_ARGS -f docker/Dockerfile.orchestrator"
BUILD_ARGS="$BUILD_ARGS -t mobilecybench-orchestrator:latest"

if [ "$NO_CACHE" = true ]; then
    BUILD_ARGS="$BUILD_ARGS --no-cache"
    echo "Building without cache..."
else
    echo "Building with cache..."
fi

# Add buildkit features for better performance
export DOCKER_BUILDKIT=1

echo ""
echo "Starting Docker build..."
echo "Command: docker build $BUILD_ARGS ."
echo ""

# Run the build
if docker build $BUILD_ARGS .; then
    echo ""
    echo "======================================="
    echo "Build completed successfully!"
    echo "======================================="
    echo ""
    echo "Image created: mobilecybench-orchestrator:latest"
    echo ""
    echo "Next steps:"
    echo "1. Run the orchestrator: ./docker/run_experiment.sh <app_name>"
    echo "2. Or use docker-compose: cd docker && docker-compose up -d"
    echo ""
else
    echo ""
    echo "======================================="
    echo "Build failed!"
    echo "======================================="
    echo ""
    echo "Please check the error messages above and try again."
    exit 1
fi