#!/bin/bash
set -e

DELTACHAT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOBILECYBENCH_ROOT="$(cd "$DELTACHAT_DIR/../.." && pwd)"

echo "=== RUNNING DeltaChat setup.sh ==="

echo "[INFO] Starting full email server (Postfix + Dovecot) for DeltaChat testing..."
docker compose -f "$DELTACHAT_DIR/docker-compose.yml" up --build -d
echo "[INFO] Email server started."

echo "[INFO] Waiting for email server to be ready..."
echo "[INFO] This may take 30-60 seconds for first startup..."
until nc -z localhost 1025 >/dev/null 2>&1 && nc -z localhost 1143 >/dev/null 2>&1; do
  sleep 5
done
echo "[INFO] Email server is up and ready (SMTP: 1025, IMAP: 1143)."

echo "[INFO] Creating test email accounts..."
cd "$MOBILECYBENCH_ROOT"
python3 "${DELTACHAT_DIR}/create_accounts.py"
if [ $? -eq 0 ]; then
  echo "[INFO] Email accounts created successfully."
else
  echo "[ERROR] Email account creation failed."
fi

echo "[INFO] Building and installing DeltaChat app from source..."
"${DELTACHAT_DIR}/setup_app_source.sh"
echo "[INFO] DeltaChat app built and ready."

echo "=== FINISHED DeltaChat setup.sh ==="