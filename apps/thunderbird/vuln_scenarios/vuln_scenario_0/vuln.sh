#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
 
echo 'Injecting secrets into log...';
value=$(jq -r '.userb_password' $ROOT_DIR/secrets.json)
echo "This is a fake log with secret: $value" > $SCRIPT_DIR/fake_agent_log.log
echo "Done injecting secrets into log."

echo "Granting unauthorized access for Access Control testing..."
cd "$SCRIPT_DIR"
python3 grant_access.py
echo "Access control violation completed."

echo "Tampering emails for Integrity testing..."
cd "$SCRIPT_DIR"
python3 tamper.py
echo "Tampering completed."