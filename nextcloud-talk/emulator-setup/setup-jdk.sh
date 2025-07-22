# #!/bin/bash

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
