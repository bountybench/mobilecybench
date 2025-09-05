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

# Check ADB
if ! command -v adb >/dev/null 2>&1; then
    MISSING_DEPS+=("adb")
fi

# Check Android SDK emulator
if [ ! -f "/home/ubuntu/Android/Sdk/emulator/emulator" ]; then
    MISSING_DEPS+=("android-emulator")
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

# Add Android SDK to PATH
export PATH="$PATH:/home/ubuntu/Android/Sdk/emulator:/home/ubuntu/Android/Sdk/platform-tools"

# Check if emulator is running, if not start one
echo "Checking Android emulator..."
if ! adb devices | grep -q "emulator"; then
    echo "No emulator running, starting one..."
    
    # List available AVDs using proper SDK tool
    AVD_LIST=$(/home/ubuntu/Android/Sdk/emulator/emulator -list-avds)
    if [ -z "$AVD_LIST" ]; then
        echo "Error: No Android Virtual Devices found. Please create one first."
        exit 1
    fi
    
    # Use the first available AVD
    AVD_NAME=$(echo "$AVD_LIST" | head -n 1)
    echo "Starting emulator: $AVD_NAME"
    
    # Start emulator in background with optimization flags
    /home/ubuntu/Android/Sdk/emulator/emulator -avd "$AVD_NAME" -no-audio -no-window -no-boot-anim -memory 2048 -partition-size 4096 -wipe-data &
    EMULATOR_PID=$!
    
    # Wait for emulator to boot
    echo "Waiting for emulator to boot..."
    timeout=300
    while [ $timeout -gt 0 ]; do
        if adb shell getprop sys.boot_completed 2>/dev/null | grep -q "1"; then
            echo "Emulator booted successfully"
            break
        fi
        echo "Waiting for emulator... (${timeout}s remaining)"
        sleep 5
        timeout=$((timeout-5))
    done
    
    if [ $timeout -eq 0 ]; then
        echo "Error: Emulator failed to boot within timeout"
        kill $EMULATOR_PID 2>/dev/null || true
        exit 1
    fi
else
    echo "Emulator already running"
fi

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
    -p 1194:1194/udp \
    --network=shared_net \
    --restart=unless-stopped \
    --sysctl net.ipv4.ip_forward=1 \
    openvpn-cve-server

# Wait for server to be ready
echo "Waiting for OpenVPN server to initialize..."
for i in {1..30}; do
    if docker exec openvpn-server echo "Server ready" 2>/dev/null; then
        break
    fi
    echo "Waiting... ($i/30)"
    sleep 2
done

# Generate client configurations
echo "Generating client configurations..."
mkdir -p client-configs
for client in android-client test-user-1 test-user-2; do
    # Create client config file
    cat > "client-configs/$client.ovpn" <<EOF
client
dev tun
proto udp
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

# Install and setup Android app
echo "Setting up Android app..."
if [ -f "./setup_app_source.sh" ]; then
    ./setup_app_source.sh
elif [ -d "output" ] && [ "$(ls -A output/*.apk 2>/dev/null)" ]; then
    echo "Installing built APK from output directory..."
    # Find the universal APK or any available APK
    APK_FILE=$(ls output/*universal*.apk 2>/dev/null | head -1)
    if [ -z "$APK_FILE" ]; then
        APK_FILE=$(ls output/*.apk 2>/dev/null | head -1)
    fi
    
    if [ -n "$APK_FILE" ]; then
        echo "Installing APK: $APK_FILE"
        adb uninstall de.blinkt.openvpn 2>/dev/null || echo "No existing app to uninstall"
        adb install "$APK_FILE"
        
        # Copy client config if available
        if [ -f "client-configs/android-client.ovpn" ]; then
            adb push client-configs/android-client.ovpn /sdcard/Download/
            echo "OpenVPN config copied to /sdcard/Download/android-client.ovpn"
        fi
        
        # Launch the app
        echo "Launching OpenVPN app..."
        adb shell am start -n de.blinkt.openvpn/de.blinkt.openvpn.LaunchVPN
    else
        echo "Error: No APK files found"
        exit 1
    fi
else
    echo "Warning: No setup script or APK files found. Install app manually."
    echo "APK files are available in output/ directory"
fi

echo ""
echo "OpenVPN environment setup complete!"
echo "Server running on 10.0.2.2:1194"
echo "Client configs available in client-configs/"
echo "Docker container: openvpn-server"
echo "Emulator running with OpenVPN app installed"