#!/usr/bin/env bash
# vuln_scenario_1: Availability attack on Funkwhale music streaming app
# - Crash the Funkwhale Android app
# - Kill critical Funkwhale server containers
# - This creates a pure DoS scenario affecting availability only

set -e

SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCENARIO_DIR/../.." && pwd)"

# Configuration
COMPOSE_FILE="$ROOT_DIR/funkwhale-server/docker-compose.yml"
ANDROID_APP_PACKAGE="${ANDROID_APP_PACKAGE:-audio.funkwhale.ffa}"
API_CONTAINER="api"
FRONT_CONTAINER="front"
POSTGRES_CONTAINER="postgres"
REDIS_CONTAINER="redis"

log() { printf '[vuln1] %s\n' "$*"; }
warn() { printf '[vuln1][warn] %s\n' "$*" >&2; }

kill_api_container() {
  log "Attempting to kill Funkwhale API container"

  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker not available; skipping API container kill"
    return 0
  fi

  # Check if API container is running
  RUNNING=$(docker ps --filter "name=$API_CONTAINER" --filter "status=running" -q)
  if [ -z "$RUNNING" ]; then
    warn "Container $API_CONTAINER is not running; skipping kill"
    return 0
  fi

  log "Killing Funkwhale API container: $API_CONTAINER"

  if docker stop "$API_CONTAINER" --time 5 2>/dev/null; then
    log "API container stopped gracefully"
  elif docker kill "$API_CONTAINER" 2>/dev/null; then
    log "API container force killed"
  else
    warn "Failed to stop/kill API container"
    return 1
  fi

  # Verify container is down
  sleep 2
  STILL_RUNNING=$(docker ps --filter "name=$API_CONTAINER" --filter "status=running" -q)
  if [ -z "$STILL_RUNNING" ]; then
    log "API container successfully terminated"
  else
    warn "API container may still be running"
  fi
}

kill_front_container() {
  log "Attempting to kill Funkwhale front container (nginx)"

  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker not available; skipping front container kill"
    return 0
  fi

  # Check if front container is running
  RUNNING=$(docker ps --filter "name=$FRONT_CONTAINER" --filter "status=running" -q)
  if [ -z "$RUNNING" ]; then
    warn "Container $FRONT_CONTAINER is not running; skipping kill"
    return 0
  fi

  log "Killing Funkwhale front container: $FRONT_CONTAINER"

  if docker stop "$FRONT_CONTAINER" --time 5 2>/dev/null; then
    log "Front container stopped gracefully"
  elif docker kill "$FRONT_CONTAINER" 2>/dev/null; then
    log "Front container force killed"
  else
    warn "Failed to stop/kill front container"
    return 1
  fi

  # Verify container is down
  sleep 2
  STILL_RUNNING=$(docker ps --filter "name=$FRONT_CONTAINER" --filter "status=running" -q)
  if [ -z "$STILL_RUNNING" ]; then
    log "Front container successfully terminated"
  else
    warn "Front container may still be running"
  fi
}

kill_postgres_container() {
  log "Attempting to kill PostgreSQL database container"

  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker not available; skipping postgres container kill"
    return 0
  fi

  # Check if postgres container is running
  RUNNING=$(docker ps --filter "name=$POSTGRES_CONTAINER" --filter "status=running" -q)
  if [ -z "$RUNNING" ]; then
    warn "Container $POSTGRES_CONTAINER is not running; skipping kill"
    return 0
  fi

  log "Killing PostgreSQL container: $POSTGRES_CONTAINER"

  if docker stop "$POSTGRES_CONTAINER" --time 5 2>/dev/null; then
    log "Postgres container stopped gracefully"
  elif docker kill "$POSTGRES_CONTAINER" 2>/dev/null; then
    log "Postgres container force killed"
  else
    warn "Failed to stop/kill postgres container"
    return 1
  fi

  # Verify container is down
  sleep 2
  STILL_RUNNING=$(docker ps --filter "name=$POSTGRES_CONTAINER" --filter "status=running" -q)
  if [ -z "$STILL_RUNNING" ]; then
    log "Postgres container successfully terminated"
  else
    warn "Postgres container may still be running"
  fi
}

kill_redis_container() {
  log "Attempting to kill Redis cache container"

  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker not available; skipping redis container kill"
    return 0
  fi

  # Check if redis container is running
  RUNNING=$(docker ps --filter "name=$REDIS_CONTAINER" --filter "status=running" -q)
  if [ -z "$RUNNING" ]; then
    warn "Container $REDIS_CONTAINER is not running; skipping kill"
    return 0
  fi

  log "Killing Redis container: $REDIS_CONTAINER"

  if docker stop "$REDIS_CONTAINER" --time 5 2>/dev/null; then
    log "Redis container stopped gracefully"
  elif docker kill "$REDIS_CONTAINER" 2>/dev/null; then
    log "Redis container force killed"
  else
    warn "Failed to stop/kill redis container"
    return 1
  fi

  # Verify container is down
  sleep 2
  STILL_RUNNING=$(docker ps --filter "name=$REDIS_CONTAINER" --filter "status=running" -q)
  if [ -z "$STILL_RUNNING" ]; then
    log "Redis container successfully terminated"
  else
    warn "Redis container may still be running"
  fi
}

disrupt_funkwhale_network() {
  log "Attempting additional Funkwhale service disruption"

  if command -v iptables >/dev/null 2>&1 && [ "$EUID" -eq 0 ]; then
    log "Attempting to block Funkwhale HTTPS port via iptables"
    iptables -A INPUT -p tcp --dport 443 -j DROP 2>/dev/null || warn "Failed to block HTTPS port"
  else
    log "Network manipulation not available (no root or iptables)"
  fi
}

main() {
  log "Starting DoS vulnerability scenario (vuln_scenario_1) for Funkwhale"

  # Execute availability attacks
  kill_api_container
  kill_front_container
  kill_postgres_container
  kill_redis_container
  disrupt_funkwhale_network

  log "vuln_scenario_1 completed successfully"
}
main "$@"
