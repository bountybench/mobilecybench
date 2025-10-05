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

# GPG Key Setup for Docker credential store
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

check_dockerd() {
    docker info > /dev/null 2>&1
    return $?
}

log_info "Checking if Docker daemon is already running..."
if check_dockerd; then
    log_info "Docker daemon is already running"
else
    log_info "Starting Docker daemon..."
    dockerd > /var/log/dockerd.log 2>&1 &

    log_info "Waiting for Docker daemon to come up..."
    timeout 30 sh -c "while (! docker info > /dev/null 2>&1); do sleep 1; done"
    if [ $? -ne 0 ]; then
        log_error "Docker daemon failed to start within 30 seconds."
        cat /var/log/dockerd.log
        exit 1
    fi
    log_info "Docker daemon is running."
fi

log_info "Starting main process: $*"
exec "$@"