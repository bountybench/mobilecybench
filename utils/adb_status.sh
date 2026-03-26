#!/usr/bin/env bash
#
# adb_status.sh — Show who owns what in the ADB + Docker network landscape.
#
# Usage:  bash utils/adb_status.sh
#
# What it shows:
#   1. Host ADB servers (processes listening on ADB ports)
#   2. Docker ADB containers (adb-server, adb-proxy, emulator, kali)
#   3. Docker networks and which ADB-related containers are on each
#   4. Port mappings (who can reach what)
#   5. A plain-English summary of the current topology
#
set -uo pipefail

BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
RESET='\033[0m'

section() { echo -e "\n${BOLD}${CYAN}── $1 ──${RESET}"; }
ok()      { echo -e "  ${GREEN}✓${RESET} $1"; }
warn()    { echo -e "  ${YELLOW}!${RESET} $1"; }
miss()    { echo -e "  ${DIM}-${RESET} $1"; }

# ── 1. Host ADB servers ─────────────────────────────────────────────────────
section "Host ADB Servers (processes listening on ADB ports)"

echo -e "${DIM}  These are ADB server processes running directly on your host.${RESET}"
echo -e "${DIM}  Port 5037 = default. Port 15037 = trusted path to containerized adb-server.${RESET}"
echo

found_host_adb=false
for port in 5037 15037; do
    # lsof: -i = internet, -P = numeric ports, -n = no DNS, -sTCP:LISTEN = only listeners
    listeners=$(lsof -i ":${port}" -P -n -sTCP:LISTEN 2>/dev/null | tail -n +2)
    if [ -n "$listeners" ]; then
        found_host_adb=true
        echo -e "  ${BOLD}Port ${port}:${RESET}"
        echo "$listeners" | while read -r line; do
            pid=$(echo "$line" | awk '{print $2}')
            cmd=$(echo "$line" | awk '{print $1}')
            user=$(echo "$line" | awk '{print $3}')
            addr=$(echo "$line" | awk '{print $9}')
            echo -e "    PID ${BOLD}${pid}${RESET}  ${cmd}  user=${user}  listening=${addr}"
        done
    else
        miss "Port ${port}: nothing listening"
    fi
done

if ! $found_host_adb; then
    echo -e "\n  ${DIM}No host ADB servers found. If you run 'adb devices' now, one will auto-start on 5037.${RESET}"
fi

# ── 2. Docker ADB containers ────────────────────────────────────────────────
section "Docker ADB Containers"

echo -e "${DIM}  Containers involved in the ADB isolation architecture.${RESET}"
echo

containers=("adb-server" "adb-proxy" "emulator-container" "kali")
roles=(
    "Dedicated ADB server on adb_net. Connects to emulator:5555. Trusted port published on 127.0.0.1:15037."
    "Filtering proxy. Blocks root/su. Bridges shared_net ↔ adb_net."
    "Android emulator. ADB transport on port 5555."
    "Agent container. Can only reach adb-proxy:5037."
)

for i in "${!containers[@]}"; do
    name="${containers[$i]}"
    role="${roles[$i]}"
    info=$(docker inspect "$name" 2>/dev/null)
    if [ $? -ne 0 ]; then
        miss "${name}: not running"
        continue
    fi

    status=$(echo "$info" | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['State']['Status'])" 2>/dev/null)
    image=$(echo "$info" | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['Config']['Image'])" 2>/dev/null)

    # Networks
    networks=$(echo "$info" | python3 -c "
import sys, json
nets = json.load(sys.stdin)[0]['NetworkSettings']['Networks']
for name, cfg in nets.items():
    ip = cfg.get('IPAddress', '?')
    print(f'{name} ({ip})')
" 2>/dev/null)

    # Published ports
    ports=$(echo "$info" | python3 -c "
import sys, json
ports = json.load(sys.stdin)[0]['NetworkSettings']['Ports'] or {}
for container_port, bindings in ports.items():
    if bindings:
        for b in bindings:
            print(f\"{b['HostIp']}:{b['HostPort']} → {container_port}\")
    else:
        print(f'{container_port} (not published)')
" 2>/dev/null)

    if [ "$status" = "running" ]; then
        ok "${BOLD}${name}${RESET}  [${GREEN}${status}${RESET}]  image=${image}"
    else
        warn "${BOLD}${name}${RESET}  [${RED}${status}${RESET}]  image=${image}"
    fi
    echo -e "    ${DIM}Role: ${role}${RESET}"
    if [ -n "$networks" ]; then
        echo "$networks" | while read -r net; do
            echo -e "    Network: ${net}"
        done
    fi
    if [ -n "$ports" ]; then
        echo "$ports" | while read -r p; do
            echo -e "    Port: ${p}"
        done
    fi
done

# ── 3. Docker networks ──────────────────────────────────────────────────────
section "Docker Networks (ADB-related)"

echo -e "${DIM}  shared_net: agent + app servers + proxy. adb_net: adb-server + proxy + emulator.${RESET}"
echo -e "${DIM}  Kali is NOT on adb_net — that's the isolation boundary.${RESET}"
echo

for net in shared_net adb_net; do
    info=$(docker network inspect "$net" 2>/dev/null)
    if [ $? -ne 0 ]; then
        miss "${net}: does not exist"
        continue
    fi

    internal=$(echo "$info" | python3 -c "import sys,json; print(json.load(sys.stdin)[0].get('Internal', False))" 2>/dev/null)
    subnet=$(echo "$info" | python3 -c "
import sys, json
cfg = json.load(sys.stdin)[0]['IPAM']['Config']
print(cfg[0]['Subnet'] if cfg else 'none')
" 2>/dev/null)

    members=$(echo "$info" | python3 -c "
import sys, json
containers = json.load(sys.stdin)[0].get('Containers', {})
for cid, c in containers.items():
    print(f\"  {c['Name']:25s} {c['IPv4Address']}\")
" 2>/dev/null)

    echo -e "  ${BOLD}${net}${RESET}  subnet=${subnet}  internal=${internal}"
    if [ -n "$members" ]; then
        echo "$members"
    else
        echo -e "    ${DIM}(no containers)${RESET}"
    fi
    echo
done

# ── 4. Connectivity summary ─────────────────────────────────────────────────
section "What 'adb devices' means from each location"

echo -e "
  ${BOLD}From host (bare 'adb'):${RESET}
    Talks to host ADB server on localhost:5037 (default).
    This is the UNTRUSTED default — if no server is running, one auto-starts.

  ${BOLD}From host (ANDROID_ADB_SERVER_PORT=15037 adb devices):${RESET}
    Talks to containerized adb-server via published port 127.0.0.1:15037.
    This is the TRUSTED path — bypasses the proxy, full access including root.

  ${BOLD}From kali container:${RESET}
    ADB_SERVER_SOCKET=tcp:adb-proxy:5037 → proxy filters → adb-server.
    Cannot reach adb-server directly (not on adb_net).
    Cannot resolve host.docker.internal (no extra_hosts).

  ${BOLD}From adb-proxy:${RESET}
    On both shared_net and adb_net. Forwards allowed commands to adb-server:5037.

  ${BOLD}Device names in 'adb devices':${RESET}
    Shows the transport label from the ADB server's perspective.
    e.g. 'host.docker.internal:5555' = native mode, 'emulator-container:5555' = container mode.
    This is just a label — it does NOT mean kali can reach that host.
"
