# #!/bin/bash

# set -e

# ANDROID_SDK_ROOT="/opt/android-sdk"
# SDK_VERSION=34
# EMULATOR_NAME="MobileCybenchEmu"
# ARCH="x86_64"  # In Docker, x86_64 is more stable than arm64

# log() {
#     echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
# }

log "Installing Java (OpenJDK)..."
apt update && apt install -y default-jdk unzip curl git wget > /dev/null

apt install default-jdk
wget https://dl.google.com/android/repository/sdk-tools-linux-4333796.zip
unzip sdk-tools-linux-4333796.zip -d android-sdk
mv android-sdk /opt/

export ANDROID_SDK_ROOT=/opt/android-sdk
echo "export ANDROID_SDK_ROOT=/opt/android-sdk" >> ~/.bashrc
echo "export PATH=$PATH:$ANDROID_SDK_ROOT/tools" >> ~/.bashrc

cd /opt/android-sdk/tools/bin
/opt/android-sdk/tools/bin/sdkmanager --update
/opt/android-sdk/tools/bin/sdkmanager --licenses
/opt/android-sdk/tools/bin/sdkmanager "system-images;android-25;google_apis;armeabi-v7a"
/opt/android-sdk/tools/bin/sdkmanager "emulator"
/opt/android-sdk/tools/bin/sdkmanager "platform-tools"

# log "Downloading Android Command Line Tools..."
# mkdir -p "$ANDROID_SDK_ROOT/cmdline-tools"
# cd "$ANDROID_SDK_ROOT"
# curl -sSL "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip" -o tools.zip

# mkdir -p cmdline-tools
# unzip -q tools.zip -d cmdline-tools-temp
# mv cmdline-tools-temp/cmdline-tools cmdline-tools/latest
# rm -rf cmdline-tools-temp tools.zip

# log "Setting up environment..."
# export PATH="$ANDROID_SDK_ROOT/cmdline-tools/latest/bin:$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/emulator:$PATH"

# log "Accepting SDK licenses..."
# yes | sdkmanager --sdk_root="$ANDROID_SDK_ROOT" --licenses > /dev/null

# log "Installing Android SDK components for SDK $SDK_VERSION..."
# sdkmanager --sdk_root="$ANDROID_SDK_ROOT" \
#   "platform-tools" \
#   "emulator" \
#   "platforms;android-${SDK_VERSION}" \
#   "build-tools;${SDK_VERSION}.0.0" \
#   "system-images;android-${SDK_VERSION};google_apis;${ARCH}" > /dev/null
