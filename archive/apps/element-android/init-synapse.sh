#!/bin/bash
set -e

# Generate signing key if it doesn't exist
if [ ! -f /data/localhost.signing.key ]; then
    echo "Generating Synapse signing key..."
    python -m synapse.app.homeserver --config-path /data/homeserver.yaml --generate-keys
fi

# Start Synapse
echo "Starting Synapse homeserver..."
exec python -m synapse.app.homeserver --config-path /data/homeserver.yaml
