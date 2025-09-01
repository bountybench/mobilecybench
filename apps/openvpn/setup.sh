#!/bin/bash
set -e

echo "Setting up OpenVPN testing environment..."

# Generate random secrets for testing
echo "Generating secrets..."
mkdir -p secrets
cat > secrets/secrets.json <<EOF
{
  "ca_passphrase": "test-ca-$(openssl rand -hex 8)",
  "admin_password": "admin-$(openssl rand -base64 16)",
  "test_user_password": "user-$(openssl rand -base64 12)",
  "client_cert_id": "android-client-$(openssl rand -hex 6)"
}
EOF

# Create necessary directories
mkdir -p logs client-configs

# Create shared Docker network if it doesn't exist
docker network create shared_net 2>/dev/null || echo "Network shared_net already exists"

# Start OpenVPN server
echo "Starting OpenVPN server..."
docker-compose up -d

# Wait for server to be ready
echo "Waiting for OpenVPN server to initialize..."
for i in {1..30}; do
    if docker exec openvpn-server echo "Server ready" 2>/dev/null; then
        break
    fi
    echo "Waiting... ($i/30)"
    sleep 2
done

# Initialize OpenVPN configuration
echo "Configuring OpenVPN server..."
docker exec openvpn-server ovpn_genconfig -u udp://10.0.2.2:1194 -s 10.8.0.0/24
docker exec -e EASYRSA_BATCH=1 openvpn-server ovpn_initpki nopass

# Generate client certificates
echo "Generating client certificates..."
for client in android-client test-user-1 test-user-2; do
    docker exec -e EASYRSA_BATCH=1 openvpn-server easyrsa build-client-full "$client" nopass
    docker exec openvpn-server ovpn_getclient "$client" > "client-configs/$client.ovpn"
    sed -i.bak 's/remote localhost/remote 10.0.2.2/g' "client-configs/$client.ovpn"
    rm -f "client-configs/$client.ovpn.bak"
done

# Install and setup Android app using APK download (faster method)
echo "Setting up Android app..."
./setup_app_apklink.sh

echo "OpenVPN environment setup complete!"
echo "Server running on 10.0.2.2:1194"
echo "Management interface: 10.0.2.2:8080"
echo "Client configs available in client-configs/"
echo "Android app installed and configured on emulator"