
#!/bin/bash
set -e

# Ensure correct Java version
if ! java -version 2>&1 | grep "17"; then
    echo "Java 17 not found, installing..."
    sudo apt-get update
    sudo apt-get install -y openjdk-17-jdk
fi

cd codebase 
# Continue with Gradle build
./gradlew  assembleRelease && cp app/build/outputs/apk/libre/release/app-libre-release-unsigned.apk ../apk/keepassdx.apk

sudo apt install google-android-build-tools-34.0.0-installer -y
cd ..
apksigner sign --ks qilsklo.keystore --ks-pass pass:qilsklo apk/keepassdx.apk

apksigner verify apk/keepassdx.apk


