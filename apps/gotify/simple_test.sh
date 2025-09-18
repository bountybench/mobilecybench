#!/bin/bash
# Simple connectivity test for Gotify server
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_PREFIX="[test]"

info() { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn() { printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
error() { printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

# Function to verify shared network connectivity
verify_shared_net_connectivity() {
    info "Testing connectivity to Gotify server via shared_net..."

    # Check if metadata.json exists
    if [ ! -f "$SCRIPT_DIR/metadata.json" ]; then
        error "metadata.json not found"
    fi

    # Extract app server URL from metadata.json
    if command -v jq >/dev/null 2>&1; then
        APP_SERVER=$(jq -r '.app_server' "$SCRIPT_DIR/metadata.json")
    else
        # Fallback if jq is not available
        APP_SERVER=$(grep '"app_server"' "$SCRIPT_DIR/metadata.json" | sed 's/.*": "*\([^"]*\)".*/\1/')
    fi

    if [ -z "$APP_SERVER" ] || [ "$APP_SERVER" = "null" ]; then
        error "app_server not found in metadata.json"
    fi

    info "Testing connectivity to: $APP_SERVER"

    # Test connectivity using a temporary container on shared_net
    if docker run --rm --network shared_net alpine:latest wget -q --spider "$APP_SERVER/health" 2>/dev/null; then
        info "✅ Successfully connected to $APP_SERVER via shared_net"
        return 0
    elif docker run --rm --network shared_net alpine:latest wget -q --spider "$APP_SERVER/" 2>/dev/null; then
        info "✅ Successfully connected to $APP_SERVER via shared_net (fallback endpoint)"
        return 0
    else
        error "❌ Cannot reach app server via shared_net: $APP_SERVER"
    fi
}

# Main test function
main() {
    info "Starting Gotify simple connectivity test..."
    verify_shared_net_connectivity
    info "✅ All tests passed!"
}

# Run main function
main "$@"