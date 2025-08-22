#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/mobilecybench"
source "${ROOT_DIR}/utils/common.sh"
source "${ROOT_DIR}/utils/wait.sh"

BRIDGE_PORT="${MCB_BRIDGE_PORT:-52888}"
BRIDGE_TOKEN_FILE="${ROOT_DIR}/ssh_key"
UDS_PATH="${ROOT_DIR}/mcb.sock"
TCP_BRIDGE_URL="http://host.docker.internal:${BRIDGE_PORT}"
UDS_BRIDGE_URL="http://localhost"
BRIDGE_TOKEN="$(cat "${BRIDGE_TOKEN_FILE}" 2>/dev/null || true)"
SHIM_PATH="/usr/local/bin/adb"

call_start_via_uds() {
    if ! command -v curl >/dev/null 2>&1; then
        log_warn "curl not available; cannot use UDS"
        return 1
    fi
    curl -sS --unix-socket "${UDS_PATH}" -H "Content-Type: application/json" \
        -X POST "${UDS_BRIDGE_URL}/start" -d '{"token":""}' -w "\n%{http_code}"
}

call_start_via_tcp() {
    if [[ -z "${BRIDGE_TOKEN}" ]]; then
        log_warn "No bridge token at ${BRIDGE_TOKEN_FILE}; cannot use TCP"
        return 1
    fi
    log_info "calling host bridge via TCP ${TCP_BRIDGE_URL}"
    curl -sS -H "Content-Type: application/json" -H "X-MCB-TOKEN: ${BRIDGE_TOKEN}" \
        -X POST "${TCP_BRIDGE_URL}/start" -d "{\"token\":\"${BRIDGE_TOKEN}\"}" -w "\n%{http_code}"
}

call_stop_via_uds() {
    if ! command -v curl >/dev/null 2>&1; then
        log_warn "curl not available; cannot use UDS"
        return 1
    fi
    curl -sS --unix-socket "${UDS_PATH}" -H "Content-Type: application/json" \
        -X POST "${UDS_BRIDGE_URL}/stop" -d '{"token":""}' -w "\n%{http_code}"
}

call_stop_via_tcp() {
    if [[ -z "${BRIDGE_TOKEN}" ]]; then
        log_warn "No bridge token at ${BRIDGE_TOKEN_FILE}; cannot use TCP"
        return 1
    fi
    log_info "calling host bridge via TCP ${TCP_BRIDGE_URL} (stop)"
    curl -sS -H "Content-Type: application/json" -H "X-MCB-TOKEN: ${BRIDGE_TOKEN}" \
        -X POST "${TCP_BRIDGE_URL}/stop" -d "{\"token\":\"${BRIDGE_TOKEN}\"}" -w "\n%{http_code}"
}

install_shim_if_missing() {
    if [[ -f "${SHIM_PATH}" ]]; then
        [[ -x "${SHIM_PATH}" ]] || chmod +x "${SHIM_PATH}" || true
        return 0
    fi
    log_warn "adb shim missing at ${SHIM_PATH}"
    return 1
}

start_proxied_adb() {
    "${SHIM_PATH}" -a -P 5037 server start >/dev/null 2>&1 || true
    local timeout="${1:-10}"
    local start_ts
    start_ts=$(date +%s)
    while :; do
        if "${SHIM_PATH}" devices >/dev/null 2>&1; then
            return 0
        fi
        if (( $(date +%s) - start_ts >= timeout )); then
            return 1
        fi
        sleep 0.05
    done
}

stop_proxied_adb() {
    "${SHIM_PATH}" -a -P 5037 server kill >/dev/null 2>&1 || true
    return 0
}

host_bridge_start() {
    log_info "Starting host-bridge start request..."

    local resp=""
    if wait_for_uds_ready 5; then
        log_info "UDS appears ready at ${UDS_PATH}; attempting UDS start..."
        resp="$(call_start_via_uds || true)"
        HTTP_STATUS="$(echo "${resp}" | tail -n1 || true)"
        if [[ ! "${HTTP_STATUS}" =~ ^2[0-9][0-9]$ ]]; then
            log_warn "UDS /start returned ${HTTP_STATUS:-no-response}; falling back to TCP"
            resp="$(call_start_via_tcp || true)"
        else
            log_info "calling host bridge via UDS ${UDS_PATH}"
        fi
    else
        log_info "UDS not ready or not supported; using TCP"
        resp="$(call_start_via_tcp || true)"
    fi

    if [[ -z "${resp}" ]]; then
        log_error "no response from host bridge"
        return 1
    fi

    HTTP_BODY=$(echo "${resp}" | sed '$d')
    HTTP_STATUS=$(echo "${resp}" | tail -n1)

    log_info "HTTP ${HTTP_STATUS} response from host bridge:"
    printf '%s\n' "${HTTP_BODY}"

    if [[ "${HTTP_STATUS}" =~ ^2[0-9][0-9]$ ]]; then
        log_info "Bridge accepted start request (HTTP ${HTTP_STATUS})."
        if install_shim_if_missing; then
            log_info "Starting proxied adb server via shim (${SHIM_PATH})..."
            if start_proxied_adb 10; then
                log_info "done (container will proxy adb calls to host bridge)."
                return 0
            else
                log_warn "ADB server did not become ready in time"
                return 1
            fi
        else
            log_warn "adb shim not present; proxying will fail"
            return 1
        fi
    else
        log_error "host bridge returned HTTP ${HTTP_STATUS}"
        log_error "Response body:"
        printf '%s\n' "${HTTP_BODY}"
        return 1
    fi
}

host_bridge_stop() {
    log_info "Sending host-bridge stop request..."

    local resp=""
    if wait_for_uds_ready 5; then
        log_info "UDS appears ready at ${UDS_PATH}; attempting UDS stop..."
        resp="$(call_stop_via_uds || true)"
        HTTP_STATUS="$(echo "${resp}" | tail -n1 || true)"
        if [[ ! "${HTTP_STATUS}" =~ ^2[0-9][0-9]$ ]]; then
            log_warn "UDS /stop returned ${HTTP_STATUS:-no-response}; falling back to TCP"
            resp="$(call_stop_via_tcp || true)"
        else
            log_info "calling host bridge via UDS ${UDS_PATH}"
        fi
    else
        log_info "UDS not ready or not supported; using TCP"
        resp="$(call_stop_via_tcp || true)"
    fi

    if [[ -z "${resp}" ]]; then
        log_error "no response from host bridge (stop)"
        return 1
    fi

    HTTP_BODY=$(echo "${resp}" | sed '$d')
    HTTP_STATUS=$(echo "${resp}" | tail -n1)

    log_info "HTTP ${HTTP_STATUS} response from host bridge (stop):"
    printf '%s\n' "${HTTP_BODY}"

    if [[ "${HTTP_STATUS}" =~ ^2[0-9][0-9]$ ]]; then
        log_info "Bridge accepted stop request (HTTP ${HTTP_STATUS})."
        stop_proxied_adb || true
        return 0
    else
        log_error "host bridge returned HTTP ${HTTP_STATUS} for stop"
        printf '%s\n' "${HTTP_BODY}"
        return 1
    fi
}