#!/bin/bash
set -e

echo "Setting up OpenVPN testing environment..."

# Check dependencies
echo "Checking dependencies..."
MISSING_DEPS=()

# Check Docker
if ! command -v docker >/dev/null 2>&1; then
    MISSING_DEPS+=("docker")
elif ! docker ps >/dev/null 2>&1; then
    echo "Error: Docker is installed but not accessible. Please run:"
    echo "  sudo usermod -aG docker \$USER"
    echo "  newgrp docker"
    echo "Or run Docker commands with sudo."
    exit 1
fi

# Check Python3
if ! command -v python3 >/dev/null 2>&1; then
    MISSING_DEPS+=("python3")
fi

if [ ${#MISSING_DEPS[@]} -ne 0 ]; then
    echo "Error: Missing dependencies: ${MISSING_DEPS[*]}"
    echo "Please install the missing dependencies and try again."
    exit 1
fi

# Generate random secrets for testing
echo "Checking secrets..."
if [ ! -f "secrets.json" ] || grep -q "YOUR_.*_HERE" secrets.json; then
    echo "Generating secrets..."
    cat > secrets.json <<EOF
{
  "ca_passphrase": "test-ca-$(openssl rand -hex 8)",
  "admin_password": "admin-$(openssl rand -base64 16)",
  "test_user_password": "user-$(openssl rand -base64 12)",
  "client_cert_id": "android-client-$(openssl rand -hex 6)"
}
EOF
else
    echo "Using existing secrets from secrets.json"
fi

# Create necessary directories
mkdir -p logs client-configs

# Create shared Docker network if it doesn't exist
docker network create shared_net 2>/dev/null || echo "Network shared_net already exists"

# Stop and remove any existing container
docker stop openvpn-server 2>/dev/null || true
docker rm openvpn-server 2>/dev/null || true

# Build official OpenVPN server for CVE testing
echo "Building official OpenVPN server..."
docker build -f Dockerfile.openvpn-server -t openvpn-cve-server .

# Start OpenVPN server
echo "Starting OpenVPN server..."
docker run -d --name openvpn-server \
    --cap-add=NET_ADMIN \
    --device=/dev/net/tun \
    -p 1194:1194/tcp \
    --network=shared_net \
    --restart=unless-stopped \
    --sysctl net.ipv4.ip_forward=1 \
    openvpn-cve-server

# Wait for server to be healthy
echo "Waiting for OpenVPN server to become healthy..."
TIMEOUT=60
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    HEALTH_STATUS=$(docker inspect --format='{{.State.Health.Status}}' openvpn-server 2>/dev/null || echo "starting")
    if [ "$HEALTH_STATUS" = "healthy" ]; then
        echo "OpenVPN server is healthy and ready"
        break
    fi
    echo "Health status: $HEALTH_STATUS (${ELAPSED}s elapsed)"
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    echo "Error: OpenVPN server failed to become healthy within ${TIMEOUT}s"
    echo "Container logs:"
    docker logs openvpn-server
    exit 1
fi

# Generate client configurations
echo "Generating client configurations..."
mkdir -p client-configs
for client in android-client test-user-1 test-user-2; do
    # Create client config file
    cat > "client-configs/$client.ovpn" <<EOF
client
dev tun
proto tcp
remote 10.0.2.2 1194
resolv-retry infinite
nobind
persist-key
persist-tun
cipher AES-256-GCM
auth SHA256
tls-version-min 1.2
remote-cert-tls server
verb 3
<ca>
$(docker exec openvpn-server cat /etc/openvpn/easy-rsa/pki/ca.crt)
</ca>
<cert>
$(docker exec openvpn-server cat /etc/openvpn/easy-rsa/pki/issued/$client.crt)
</cert>
<key>
$(docker exec openvpn-server cat /etc/openvpn/easy-rsa/pki/private/$client.key)
</key>
EOF
done

echo ""
echo "OpenVPN server setup complete!"
echo ""
echo "Server Details:"
echo "  - Docker container: openvpn-server"
echo "  - Server address: 10.0.2.2:1194 (for emulator)"
echo "  - Client configs: client-configs/"
echo ""
echo "To build the Android app:"
echo "  ./setup_app_source.sh"
echo ""

# Auto-install APK if emulator is running and APK exists
if adb devices 2>/dev/null | grep -q "emulator"; then
    echo "Emulator detected - checking for APK to install..."

    if [ -f "apk/openvpn.apk" ]; then
        echo "Installing OpenVPN APK on emulator..."
        adb uninstall de.blinkt.openvpn 2>/dev/null || echo "No existing app to uninstall"
        adb install apk/openvpn.apk

        if [ -f "client-configs/android-client.ovpn" ]; then
            echo "Copying OpenVPN client config to emulator..."
            adb push client-configs/android-client.ovpn /sdcard/Download/
            echo "✓ OpenVPN app installed and config copied"
        else
            echo "✓ OpenVPN app installed (client config not yet generated)"
        fi
    else
        echo "No APK found at apk/openvpn.apk - skipping installation"
        echo "Run ./setup_app_source.sh or ./setup_app_apklink.sh to build/download the APK"
    fi
else
    echo "To install the APK (requires adb and emulator):"
    echo "  adb install apk/openvpn.apk"
    echo "  adb push client-configs/android-client.ovpn /sdcard/Download/"
fi