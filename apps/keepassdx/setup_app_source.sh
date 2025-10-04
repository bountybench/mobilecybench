
#!/bin/bash
set -e


cd codebase 
# Continue with Gradle build
./gradlew  assembleRelease && cp app/build/outputs/apk/libre/release/app-libre-release-unsigned.apk ../apk/keepassdx.apk

sudo apt install google-android-build-tools-34.0.0-installer -y
cd ..
apksigner sign --ks qilsklo.keystore --ks-pass pass:qilsklo apk/keepassdx.apk

apksigner verify apk/keepassdx.apk


