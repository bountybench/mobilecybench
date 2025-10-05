#!/usr/bin/env bash
set -euo pipefail
TOOL_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="/mobilecybench"
if [[ ! -f "/.dockerenv" ]]; then
    ROOT_DIR="$(git -C "$TOOL_SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"
fi
source "${ROOT_DIR}/utils/common.sh"

# SSH Key Setup
mkdir -p /root/.ssh
chmod 700 /root/.ssh
if [ -f /root/.ssh/id_rsa ]; then
  chmod 600 /root/.ssh/id_rsa
  eval "$(ssh-agent -s)"
  ssh-add /root/.ssh/id_rsa
  log_info "SSH key loaded."
else
  log_info "No SSH key at /root/.ssh/id_rsa – skipping."
fi

# GPG Key Setup for Docker credential store (optional - skip if pass not available)
if command -v pass >/dev/null 2>&1; then
    log_info "Setting up Docker credential store with pass..."
    gpg --batch --passphrase '' \
        --quick-gen-key "Docker Helper (machine)" default default 0 && \
    FPR=$(gpg --list-secret-keys --with-colons | awk -F: '/^fpr:/ {print $10; exit}') && \
    pass init "$FPR" && \
    curl -fsSL "$(curl -s https://api.github.com/repos/docker/docker-credential-helpers/releases/latest \
                   | grep browser_download_url \
                   | grep 'docker-credential-pass.*linux-'$(dpkg --print-architecture) \
                   | cut -d '"' -f 4)" \
         -o /usr/local/bin/docker-credential-pass && \
    chmod +x /usr/local/bin/docker-credential-pass && \
    mkdir -p /root/.docker && \
    echo '{"credsStore":"pass"}' > /root/.docker/config.json
    log_info "Docker credential store configured."
else
    log_info "pass command not found - skipping Docker credential store setup."
fi

check_dockerd() {
    docker info > /dev/null 2>&1
    return $?
}

log_info "Checking if Docker daemon is already running..."
if check_dockerd; then
    log_info "Docker daemon is already running"
else
    log_info "Configuring iptables to use legacy mode (for macOS compatibility)..."
    # Use iptables-legacy to avoid nftables issues on macOS/ARM64
    update-alternatives --set iptables /usr/sbin/iptables-legacy 2>/dev/null || true
    update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy 2>/dev/null || true

    log_info "Starting Docker daemon..."
    # Disable iptables to work around kernel module issues in Docker-in-Docker on macOS
    dockerd --iptables=false --ip-masq=false > /var/log/dockerd.log 2>&1 &
    DOCKERD_PID=$!
    log_info "Docker daemon started with PID: $DOCKERD_PID"

    log_info "Waiting for Docker daemon to come up (max 60 seconds)..."
    ELAPSED=0
    while [ $ELAPSED -lt 60 ]; do
        if docker info > /dev/null 2>&1; then
            log_info "Docker daemon is ready!"
            break
        fi

        # Check if dockerd process is still running
        if ! kill -0 $DOCKERD_PID 2>/dev/null; then
            log_error "Docker daemon process died!"
            log_error "Last 50 lines of dockerd log:"
            tail -50 /var/log/dockerd.log
            exit 1
        fi

        echo -n "."
        sleep 2
        ELAPSED=$((ELAPSED + 2))
    done
    echo ""

    if [ $ELAPSED -ge 60 ]; then
        log_error "Docker daemon failed to become ready within 60 seconds."
        log_error "dockerd is still running but not responding. Last 50 lines of log:"
        tail -50 /var/log/dockerd.log
        exit 1
    fi

    log_info "Docker daemon is running and ready."
fi

log_info "Starting main process: $*"
exec "$@"