#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "Cleaning up FairEmail environment..."

# Tear down Docker services
if [ -f "docker-compose.yml" ]; then
    docker compose down -v
fi

# Clean up generated certificates
rm -rf dms-config/ssl/demoCA
rm -f dms-config/ssl/*-cert.pem dms-config/ssl/*-key.pem dms-config/ssl/*.csr

# Clean up dms-config
rm -f dms-config/postfix-accounts.cf

# Clean up local.properties in codebase
rm -f codebase/local.properties

echo "Cleanup complete."
