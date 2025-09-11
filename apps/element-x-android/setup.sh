#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
LOG_PREFIX="[setup]"

# Source android utilities
source "$ROOT_DIR/utils/android.sh" 2>/dev/null || true

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

setup_matrix_server() {
    info "Setting up Matrix server..."
    
    # Check Docker
    docker info >/dev/null 2>&1 || error "Docker is not running"
    
    # Create network
    docker network create shared_net 2>/dev/null || true
    
    # Install Python deps
    python3 -m pip install --break-system-packages uiautomator2 requests >/dev/null 2>&1 || true
    
    # Generate config if needed
    if [[ ! -f "${SCRIPT_DIR}/synapse/homeserver.yaml" ]]; then
        info "Generating Matrix config..."
        mkdir -p "${SCRIPT_DIR}/synapse"
        docker run --rm -v "${SCRIPT_DIR}/synapse:/data" \
            -e SYNAPSE_SERVER_NAME=localhost \
            -e SYNAPSE_REPORT_STATS=no \
            matrixdotorg/synapse:latest generate
    fi
    
    # Copy log config
    cp "${SCRIPT_DIR}/synapse_log.config" "${SCRIPT_DIR}/synapse/localhost.log.config"
    
    # Start services
    info "Starting Matrix server..."
    cd "$SCRIPT_DIR"
    docker-compose up -d --build
    
    # Wait for server (longer timeout for ephemeral setup)
    info "Waiting for Matrix server..."
    for i in {1..18}; do
        if curl -sf http://localhost:8008/_matrix/client/versions >/dev/null 2>&1; then
            info "Matrix server ready"
            break
        elif [[ $i -eq 18 ]]; then
            error "Matrix server failed to start"
        fi
        sleep 5
    done
    
    # Setup users and rooms
    info "Creating users and rooms..."
    python3 "${SCRIPT_DIR}/setup_users.py"
}

install_and_launch_app() {
    info "Installing Element X on emulator..."
    
    # Check emulator
    if ! adb devices | grep -q "emulator"; then
        warn "No emulator detected"
        info "Start emulator and run setup.sh again"
        return 1
    fi
    
    # Detect device architecture
    DEVICE_ARCH=$(adb shell getprop ro.product.cpu.abi | tr -d '\r\n')
    info "Detected device architecture: $DEVICE_ARCH"
    
    # Find correct APK - prefer device architecture, fallback to universal
    APK_PATH=$(find "$SCRIPT_DIR/codebase" -name "*-$DEVICE_ARCH-debug.apk" | head -1)
    if [[ -z "$APK_PATH" ]]; then
        info "No $DEVICE_ARCH APK found, trying universal APK"
        APK_PATH=$(find "$SCRIPT_DIR/codebase" -name "*universal*debug.apk" | head -1)
    fi
    [[ -n "$APK_PATH" ]] || error "No suitable APK found. Run setup_app_source.sh first"
    
    info "Installing: $(basename "$APK_PATH")"
    adb install -r -t "$APK_PATH" || error "APK installation failed"
    
    # Clear app data and launch fresh
    info "Clearing Element X app data for fresh start..."
    adb shell am force-stop io.element.android.x.debug 2>/dev/null || true
    adb shell pm clear io.element.android.x.debug 2>/dev/null || true
    
    info "Launching Element X..."
    adb shell am start -n io.element.android.x.debug/io.element.android.x.MainActivity
    sleep 5
    
    # Attempt login
    info "Attempting automatic login..."
    if python3 "${SCRIPT_DIR}/elementx_login.py" --server http://10.0.2.2:8008 --username agent --password agentpass; then
        info "✅ Login successful!"
    else
        info "⚠️ Manual login required"
        info "Server: http://10.0.2.2:8008"
        info "Username: agent"
        info "Password: agentpass"
    fi
}

main() {
    info "Setting up Element X Android environment..."
    
    setup_matrix_server
    
    if install_and_launch_app; then
        info "🎉 Setup completed!"
        info "📱 Element X running on emulator"
        info "🌐 Matrix server: http://localhost:8008"
    else
        info "🎉 Matrix server setup completed!"
        info "🌐 Server: http://localhost:8008"
        info "👤 Agent: agent / agentpass"
    fi
}

main "$@"