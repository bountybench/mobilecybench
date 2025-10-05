#!/bin/bash
# Fixed experiment runner with retry logic and error handling
set -e

APP_NAME="$1"
CONFIG_FILE="${2:-runner_config.json}"

echo "============================================"
echo "Running experiment for: $APP_NAME"
echo "Config file: $CONFIG_FILE"
echo "============================================"
echo ""

cd /mobilecybench

# Step 1: Setup Android SDK with retry logic
echo "Setting up Android SDK..."
export ANDROID_HOME=/root/.android-sdk
export PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools

# Accept licenses
yes | sdkmanager --licenses >/dev/null 2>&1 || true

# Install packages one by one with retries
echo "Installing Android SDK packages..."
packages=(
    "platform-tools"
    "emulator"
    "platforms;android-35"
    "system-images;android-35;google_apis;x86_64"
    "build-tools;35.0.0"
)

for package in "${packages[@]}"; do
    echo "Installing $package..."
    retries=3
    for i in $(seq 1 $retries); do
        if sdkmanager "$package" 2>&1; then
            echo "Successfully installed $package"
            break
        else
            echo "Failed to install $package (attempt $i of $retries)"
            if [ $i -eq $retries ]; then
                echo "ERROR: Could not install $package after $retries attempts"
                # For now, continue anyway to see how far we get
            else
                echo "Retrying in 5 seconds..."
                sleep 5
            fi
        fi
    done
done

# Create emulator if it doesn't exist
if ! avdmanager list avd | grep -q "test_avd"; then
    echo "Creating emulator..."
    echo no | avdmanager create avd -n test_avd -k "system-images;android-35;google_apis;x86_64" --device "pixel_6" || true
fi

# Step 2: Setup app backend
echo "Setting up app backend..."
cd /mobilecybench/apps/$APP_NAME
if [ -f setup_app.sh ]; then
    ./setup_app.sh
elif [ -f setup.sh ]; then
    ./setup.sh
fi
cd /mobilecybench

# Step 3: Start emulator
echo "Starting emulator..."
./start_emulator.sh --yes || echo "Emulator start failed, continuing..."

# Step 4: Run experiment
echo "Running experiment with runner.py..."
python3 runner.py "$APP_NAME" "$CONFIG_FILE"

echo ""
echo "============================================"
echo "Experiment complete!"
echo "============================================"