#!/bin/bash
set -euo pipefail

# Entrypoint script for Containerized Codex Agent
# This script initializes the container environment and starts the Codex agent

echo "=========================================="
echo "Starting Containerized Codex Agent"
echo "=========================================="

# Environment validation
echo "Validating environment..."

# Check for required environment variables
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    echo "ERROR: OPENAI_API_KEY environment variable is required"
    echo "Please set OPENAI_API_KEY when running the container"
    exit 1
fi

if [[ -z "${APP_NAME:-}" ]]; then
    echo "WARNING: APP_NAME not set, defaulting to 'termux'"
    export APP_NAME="termux"
fi

echo "✓ Environment validated"
echo "  App: ${APP_NAME}"
echo "  API Key: [REDACTED]"

# Check if app codebase exists
if [[ ! -d "/app/codebase" ]]; then
    echo "ERROR: App codebase not found at /app/codebase"
    echo "Ensure the app source code was copied during build"
    exit 1
fi

echo "✓ App codebase found at /app/codebase"

# Wait for Kali security container to be ready
echo "Waiting for Kali security container..."
MCP_SERVER_URL="${MCP_SERVER_URL:-http://kali-security:8000/mcp}"

# Try to connect to MCP server (with retries)
for i in {1..30}; do
    if curl -s --connect-timeout 5 "${MCP_SERVER_URL}" >/dev/null 2>&1; then
        echo "✓ Kali security container is ready"
        break
    fi

    if [[ $i -eq 30 ]]; then
        echo "ERROR: Could not connect to Kali security container after 30 attempts"
        echo "URL: ${MCP_SERVER_URL}"
        exit 1
    fi

    echo "  Attempt $i/30: Waiting for Kali container..."
    sleep 2
done

# Verify Codex CLI installation
echo "Verifying Codex CLI..."
if ! command -v codex >/dev/null 2>&1; then
    echo "ERROR: Codex CLI not found in PATH"
    echo "Available commands:"
    ls -la /usr/local/bin/ | grep -E "(codex|claude)" || echo "  No Codex/Claude binaries found"
    exit 1
fi

echo "✓ Codex CLI found: $(codex --version 2>/dev/null || echo 'version check failed')"

# Check Codex configuration
if [[ ! -f "/root/.codex/config.toml" ]]; then
    echo "ERROR: Codex configuration not found at /root/.codex/config.toml"
    exit 1
fi

echo "✓ Codex configuration loaded"

# Set up Python path
export PYTHONPATH="/app:${PYTHONPATH:-}"

# Log environment info
echo "Container environment:"
echo "  Working directory: $(pwd)"
echo "  Python path: ${PYTHONPATH}"
echo "  App codebase: $(ls -la /app/codebase | wc -l) files"

# Start the Codex agent
echo "=========================================="
echo "Starting Codex Mobile Security Agent"
echo "=========================================="

# Change to app directory
cd /app

# Execute the main agent
exec python3 codex_agent.py "$@"