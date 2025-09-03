#!/bin/bash
set -e

echo "Setting up OpenVPN testing environment..."

# Check dependencies
echo "Checking dependencies..."
MISSING_DEPS=()

# Check Docker
if ! command -v docker >/dev/null 2>&1; then
    MISSING_DEPS+=("docker")
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
    
    # List available AVDs
    AVDS=(/home/ubuntu/.android/avd/*.avd)
    if [ ${#AVDS[@]} -eq 0 ]; then
        echo "Error: No Android Virtual Devices found. Please create one first."
        exit 1
    fi
    
    # Use the first available AVD
    AVD_NAME=$(basename "${AVDS[0]}" .avd)
    echo "Starting emulator: $AVD_NAME"
    
    # Start emulator in background
    /home/ubuntu/Android/Sdk/emulator/emulator -avd "$AVD_NAME" -no-audio -no-window &
    EMULATOR_PID=$!
    
    # Wait for emulator to boot
    echo "Waiting for emulator to boot..."
    timeout=180
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

# Initialize OpenVPN configuration with temporary containers
echo "Initializing OpenVPN configuration..."
docker run --rm -v openvpn-data:/etc/openvpn kylemanna/openvpn:latest ovpn_genconfig -u udp://10.0.2.2:1194 -s 10.8.0.0/24
docker run --rm -v openvpn-data:/etc/openvpn -e EASYRSA_BATCH=1 kylemanna/openvpn:latest ovpn_initpki nopass

# Start OpenVPN server
echo "Starting OpenVPN server..."
docker run -d --name openvpn-server --cap-add=NET_ADMIN --device=/dev/net/tun -p 1194:1194/udp -p 8080:8080 --network=shared_net --restart=unless-stopped -v openvpn-data:/etc/openvpn kylemanna/openvpn:latest

# Wait for server to be ready
echo "Waiting for OpenVPN server to initialize..."
for i in {1..30}; do
    if docker exec openvpn-server echo "Server ready" 2>/dev/null; then
        break
    fi
    echo "Waiting... ($i/30)"
    sleep 2
done

# Generate client certificates
echo "Generating client certificates..."
for client in android-client test-user-1 test-user-2; do
    docker exec -e EASYRSA_BATCH=1 openvpn-server easyrsa build-client-full "$client" nopass
    docker exec openvpn-server ovpn_getclient "$client" > "client-configs/$client.ovpn"
    sed -i.bak 's/remote localhost/remote 10.0.2.2/g' "client-configs/$client.ovpn"
    rm -f "client-configs/$client.ovpn.bak"
done

# Install and setup Android app
echo "Setting up Android app..."
if [ -f "./setup_app_apklink.sh" ]; then
    ./setup_app_apklink.sh
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