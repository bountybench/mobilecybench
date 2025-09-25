#!/bin/bash
set -e



SDK_ROOT="../../android-sdk"
CMDLINE_TOOLS="$SDK_ROOT/cmdline-tools"
TOOLS_VERSION="latest"
PROJECT_ROOT="$PWD/codebase"
PARENT=$PWD
#export ANDROID_HOME="$SDK_ROOT"

# Change to the codebase directory where the React Native project is located.
cd codebase || { echo "Error: codebase directory not found."; exit 1; }

echo "Installing node modules"
npm install
npm install @react-native-community/cli --save-dev

cd android

# Make sure all dependencies are installed.
# This assumes 'npm install' or 'yarn install' has already been run by a preceding step if necessary.

echo "MATTERMOST_RELEASE_STORE_FILE=$PARENT/qilsklo.keystore" > $HOME/.gradle/gradle.properties
echo "MATTERMOST_RELEASE_KEY_ALIAS=qilsklo" >> $HOME/.gradle/gradle.properties
echo "MATTERMOST_RELEASE_PASSWORD=qilsklo" >> $HOME/.gradle/gradle.properties
export APP_NAME="Mattermost Beta"
export MAIN_APP_IDENTIFIER="com.mattermost.rnbeta"
export SUPPLY_PACKAGE_NAME=$MAIN_APP_IDENTIFIER
export SUPPLY_JSON_KEY="$PARENT/google-services.json"
npx expo install expo-file-system
# Build the APK. 'assembleRelease' is the standard for release builds.
# 'assembleDebug' can also be used if needed.
# We are building without an emulator since the 'run_ci_local.sh' script handles that.
./gradlew assembleRelease

echo "✅ Mattermost APK built successfully."
