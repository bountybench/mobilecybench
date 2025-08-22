#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/mobilecybench"
AGENT_PORT="${MCB_AGENT_PORT:-52888}"
AGENT_TOKEN_FILE="${REPO_ROOT}/ssh_key"
UDS_PATH="${REPO_ROOT}/mcb.sock"
TCP_AGENT_URL="http://host.docker.internal:${AGENT_PORT}"
UDS_AGENT_URL="http://localhost"
AGENT_TOKEN="$(cat "${AGENT_TOKEN_FILE}" 2>/dev/null || true)"

SHIM_PATH="/usr/local/bin/adb"

call_start_via_uds() {
    if ! command -v curl >/dev/null 2>&1; then
        echo "[host_bridge] curl not available; cannot use UDS"
        return 1
    fi
    curl -sS --unix-socket "${UDS_PATH}" -H "Content-Type: application/json" -X POST "${UDS_AGENT_URL}/start" -d '{"token":""}' -w "\n%{http_code}" || return 1
}

call_start_via_tcp() {
    if [[ -z "${AGENT_TOKEN}" ]]; then
        echo "[host_bridge] No agent token found; cannot use TCP"
        return 1
    fi
    echo "[host_bridge] calling host agent via TCP ${TCP_AGENT_URL}"
    curl -sS -H "Content-Type: application/json" -H "X-MCB-TOKEN: ${AGENT_TOKEN}" -X POST "${TCP_AGENT_URL}/start" -d "{\"token\":\"${AGENT_TOKEN}\"}" -w "\n%{http_code}" || return 1
}

echo "[host_bridge] Starting host-agent start request..."

RESP=""
if [[ -S "${UDS_PATH}" ]]; then
    echo "[host_bridge] UDS socket exists at ${UDS_PATH}; attempting UDS start (retries)..."
    for i in 1 2 3 4 5; do
        RESP="$(call_start_via_uds 2>/dev/null || true)"
        HTTP_STATUS="$(echo "${RESP}" | tail -n1 || true)"
        if [[ "${HTTP_STATUS}" =~ ^2[0-9][0-9]$ ]]; then
            echo "[host_bridge] calling host agent via UDS ${UDS_PATH}"
            break
        fi
        sleep 0.5
    done
fi

if [[ -z "${RESP}" ]]; then
    RESP="$(call_start_via_tcp || true)"
fi

if [[ -z "${RESP}" ]]; then
    echo "[host_bridge] ERROR: no response from host agent"
    exit 1
fi

HTTP_BODY=$(echo "${RESP}" | sed '$d')
HTTP_STATUS=$(echo "${RESP}" | tail -n1)

echo "[host_bridge] HTTP ${HTTP_STATUS} response from host agent:"
echo "${HTTP_BODY}"

if [[ "${HTTP_STATUS}" =~ ^2[0-9][0-9]$ ]]; then
    echo "[host_bridge] Agent accepted start request (HTTP ${HTTP_STATUS})."
    sleep 2

    # Ensure shim is present and executable. Do not overwrite it from the container.
    if [[ -f "${SHIM_PATH}" ]]; then
        if [[ ! -x "${SHIM_PATH}" ]]; then
            chmod +x "${SHIM_PATH}" || true
        fi
        echo "[host_bridge] Starting proxied adb server via shim (${SHIM_PATH})..."
        "${SHIM_PATH}" -a -P 5037 server start || true
        echo "[host_bridge] done (container will proxy adb calls to host agent)."
        exit 0
    else
        echo "[host_bridge] WARNING: adb shim not found at ${SHIM_PATH}; proxying will fail"
        exit 1
    fi
else
    echo "[host_bridge] ERROR: host agent returned HTTP ${HTTP_STATUS}"
    echo "[host_bridge] Response body:"
    echo "${HTTP_BODY}"
    exit 1
fi