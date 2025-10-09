#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "============================================"
echo "MobileCybench Docker Experiment Runner"
echo "============================================"

# Default values
APP_NAME=""
CONFIG_FILE="runner_config.json"
USE_KVM=true
HEADLESS_MODE=true
SKIP_BUILD=false
INTERACTIVE=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --config=*)
            CONFIG_FILE="${1#*=}"
            shift
            ;;
        --no-kvm)
            USE_KVM=false
            shift
            ;;
        --gui)
            HEADLESS_MODE=false
            shift
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --interactive|-it)
            INTERACTIVE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 APP_NAME [OPTIONS]"
            echo ""
            echo "Arguments:"
            echo "  APP_NAME              Name of the app to test (from apps/ directory)"
            echo ""
            echo "Options:"
            echo "  --config FILE         Path to runner config file (default: runner_config.json)"
            echo "  --no-kvm              Disable KVM acceleration for emulator"
            echo "  --gui                 Run with GUI support (disable headless mode)"
            echo "  --skip-build          Skip building the Docker image"
            echo "  --interactive, -it    Run in interactive mode (attach to container)"
            echo "  -h, --help            Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0 conversations                    # Run experiments for conversations app"
            echo "  $0 wordpress --config custom.json   # Use custom config"
            echo "  $0 owncloud-android --no-kvm        # Run without KVM"
            echo "  $0 app --interactive                # Run interactively for debugging"
            echo ""
            echo "Available apps:"
            if [[ -d "${PROJECT_ROOT}/apps" ]]; then
                for app_dir in "${PROJECT_ROOT}/apps"/*; do
                    if [[ -d "$app_dir" && -f "$app_dir/metadata.json" ]]; then
                        echo "  - $(basename "$app_dir")"
                    fi
                done
            fi
            exit 0
            ;;
        *)
            if [[ -z "$APP_NAME" ]]; then
                APP_NAME="$1"
            else
                echo "Unknown option: $1"
                echo "Use -h or --help for usage information"
                exit 1
            fi
            shift
            ;;
    esac
done

# Validate app name
if [[ -z "$APP_NAME" ]]; then
    echo "ERROR: App name is required"
    echo "Use -h or --help for usage information"
    exit 1
fi

if [[ ! -d "${PROJECT_ROOT}/apps/${APP_NAME}" ]]; then
    echo "ERROR: App directory not found: ${PROJECT_ROOT}/apps/${APP_NAME}"
    echo ""
    echo "Available apps:"
    if [[ -d "${PROJECT_ROOT}/apps" ]]; then
        for app_dir in "${PROJECT_ROOT}/apps"/*; do
            if [[ -d "$app_dir" && -f "$app_dir/metadata.json" ]]; then
                echo "  - $(basename "$app_dir")"
            fi
        done
    fi
    exit 1
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "ERROR: Docker daemon is not running"
    echo "Please start Docker and try again"
    exit 1
fi

# Build image if needed
if [ "$SKIP_BUILD" = false ]; then
    echo "Building Docker image..."
    if ! "${SCRIPT_DIR}/build_orchestrator.sh"; then
        echo "ERROR: Failed to build Docker image"
        exit 1
    fi
else
    echo "Skipping Docker build (--skip-build flag set)"
fi

# Check if image exists
if ! docker image inspect mobilecybench-orchestrator:latest > /dev/null 2>&1; then
    echo "ERROR: Docker image not found. Please build it first:"
    echo "  ${SCRIPT_DIR}/build_orchestrator.sh"
    exit 1
fi

# Create shared network if it doesn't exist
if ! docker network inspect shared_net > /dev/null 2>&1; then
    echo "Creating shared network..."
    docker network create shared_net
fi

# Prepare environment variables
ENV_FILE="${PROJECT_ROOT}/.env"
if [[ -f "$ENV_FILE" ]]; then
    echo "Loading environment from .env file..."
    set -a
    source "$ENV_FILE"
    set +a
else
    echo "WARNING: No .env file found at $ENV_FILE"
    echo "OPENAI_API_KEY will need to be set in environment"
fi

# Check for OPENAI_API_KEY
if [[ -z "${OPENAI_API_KEY}" ]]; then
    echo "WARNING: OPENAI_API_KEY is not set"
    read -p "Do you want to continue without it? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Exiting. Please set OPENAI_API_KEY in .env or environment"
        exit 1
    fi
fi

echo ""
echo "Configuration:"
echo "  App: $APP_NAME"
echo "  Config: $CONFIG_FILE"
echo "  KVM: $USE_KVM"
echo "  Headless: $HEADLESS_MODE"
echo "  Interactive: $INTERACTIVE"
echo ""

# Docker run arguments
DOCKER_ARGS="--rm --privileged"
DOCKER_ARGS="$DOCKER_ARGS --name mobilecybench-runner-$$"
DOCKER_ARGS="$DOCKER_ARGS -v ${PROJECT_ROOT}:/mobilecybench:rw"
DOCKER_ARGS="$DOCKER_ARGS -v /var/run/docker.sock:/var/run/docker.sock"
DOCKER_ARGS="$DOCKER_ARGS --shm-size=2gb"

# Add environment variables
DOCKER_ARGS="$DOCKER_ARGS -e OPENAI_API_KEY=${OPENAI_API_KEY}"
DOCKER_ARGS="$DOCKER_ARGS -e HEADLESS_MODE=${HEADLESS_MODE}"
DOCKER_ARGS="$DOCKER_ARGS -e APP_NAME=${APP_NAME}"

# Add KVM device if available and requested
if [ "$USE_KVM" = true ] && [ -e /dev/kvm ]; then
    echo "KVM device found, enabling hardware acceleration"
    DOCKER_ARGS="$DOCKER_ARGS --device /dev/kvm"
else
    if [ "$USE_KVM" = true ]; then
        echo "WARNING: KVM device not found, emulator will run without hardware acceleration"
    else
        echo "KVM disabled by user request"
    fi
fi

# Add display for GUI mode
if [ "$HEADLESS_MODE" = false ]; then
    if [[ -n "$DISPLAY" ]]; then
        DOCKER_ARGS="$DOCKER_ARGS -e DISPLAY=$DISPLAY"
        DOCKER_ARGS="$DOCKER_ARGS -v /tmp/.X11-unix:/tmp/.X11-unix:rw"
        echo "GUI mode enabled with DISPLAY=$DISPLAY"

        # Allow X server connections
        if command -v xhost > /dev/null 2>&1; then
            xhost +local:docker 2>/dev/null || true
        fi
    else
        echo "WARNING: DISPLAY not set, falling back to headless mode"
        HEADLESS_MODE=true
        DOCKER_ARGS="$DOCKER_ARGS -e HEADLESS_MODE=true"
    fi
fi

# Add network
DOCKER_ARGS="$DOCKER_ARGS --network shared_net"

# Add interactive flags if requested
if [ "$INTERACTIVE" = true ]; then
    DOCKER_ARGS="$DOCKER_ARGS -it"
fi

# Prepare command to run inside container
CONTAINER_CMD="cd /mobilecybench && python runner.py ${APP_NAME} ${CONFIG_FILE}"

echo "Starting Docker container..."
echo "Command: docker run $DOCKER_ARGS mobilecybench-orchestrator:latest bash -c \"$CONTAINER_CMD\""
echo ""

# Run the experiment
if [ "$INTERACTIVE" = true ]; then
    # Interactive mode - attach to container
    docker run $DOCKER_ARGS mobilecybench-orchestrator:latest bash -c "$CONTAINER_CMD || bash"
else
    # Non-interactive mode - just run the command
    docker run $DOCKER_ARGS mobilecybench-orchestrator:latest bash -c "$CONTAINER_CMD"
fi

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "============================================"
    echo "Experiment completed successfully!"
    echo "============================================"
else
    echo "============================================"
    echo "Experiment failed with exit code: $EXIT_CODE"
    echo "============================================"
fi

exit $EXIT_CODE