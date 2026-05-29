#!/bin/bash
# Pull fresh OAuth tokens from macOS Keychain and update the GKE secret
# (mobilecybench/claude-code-oauth). Idempotent — safe to run anytime.
#
# Usage: bash ops/refresh_gke_oauth.sh
#
# Note: this only refreshes the K8s secret. EXISTING running pods continue
# to use whatever token they were started with — restart any pods that need
# a fresh token. New pods picked up after this command will get the new token.

set -e
NAMESPACE="${NAMESPACE:-mobilecybench}"
SECRET_NAME="${SECRET_NAME:-claude-code-oauth}"

echo "Refreshing OAuth token from macOS Keychain..."
BLOB=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null) || {
    echo "ERROR: Could not read keychain. Is Claude Code installed and authed?"
    exit 1
}
ACCESS=$(echo "$BLOB" | jq -r .claudeAiOauth.accessToken)
REFRESH=$(echo "$BLOB" | jq -r .claudeAiOauth.refreshToken)
EXP_MS=$(echo "$BLOB" | jq -r .claudeAiOauth.expiresAt)
EXP_S=$((EXP_MS / 1000))
HRS_LEFT=$(awk -v s="$((EXP_S - $(date +%s)))" 'BEGIN{printf "%.1f", s/3600}')

if [ -z "$ACCESS" ] || [ "$ACCESS" = "null" ]; then
    echo "ERROR: Empty accessToken in keychain. Open Claude Code on your Mac, sign in, retry."
    exit 1
fi

echo "  access token ends ...${ACCESS: -10}"
echo "  expires in ${HRS_LEFT}h (at $(date -r $EXP_S))"
echo ""

echo "Updating k8s secret $NAMESPACE/$SECRET_NAME..."
kubectl create secret generic "$SECRET_NAME" \
    --namespace="$NAMESPACE" \
    --from-literal=CLAUDE_CODE_OAUTH_TOKEN="$ACCESS" \
    --from-literal=CLAUDE_CODE_OAUTH_REFRESH_TOKEN="$REFRESH" \
    --dry-run=client -o yaml | kubectl apply -f -

echo ""
echo "✓ Secret updated. NEW pods will use the fresh token."
echo "  Running pods keep their pre-update token (delete + recreate to refresh them)."
