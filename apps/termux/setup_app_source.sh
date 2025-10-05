#!/bin/bash
set -e

echo "Setting up Termux app source code..."

# Check if codebase submodule exists
if [ ! -d "codebase" ]; then
    echo "Error: codebase submodule not found"
    echo "Please run: git submodule update --init --recursive"
    exit 1
fi

cd codebase

# Check prerequisites
check_prerequisites() {
    echo "Checking prerequisites..."
    
    # Check Java 17
    if ! command -v java >/dev/null 2>&1; then
        echo "ERROR: Java not found. Please install Java 17."
    exit 1
fi

    # Verify Java version (AGP 8.0+ requires Java 17+)
    java_version=$(java -version 2>&1 | head -n1 | cut -d'"' -f2 | cut -d'.' -f1)
    if [[ "$java_version" -lt 17 ]]; then
        echo "ERROR: AGP 8.0+ requires Java 17+, but found Java $java_version"
        echo "Please upgrade to Java 17 or higher."
        exit 1
    elif [[ "$java_version" -gt 17 ]]; then
        echo "WARNING: Expected Java 17, but found Java $java_version"
        echo "This should work with AGP 8.0+, but Java 17 is recommended."
    else
        echo "Java version $java_version is compatible with AGP 8.0+"
    fi
    
    # Clean up NDK environment variables that might point to old NDK
    echo "Cleaning up NDK environment variables..."
    unset ANDROID_NDK_HOME ANDROID_NDK NDK_HOME
    
    # Install Apple Silicon compatible NDK if not present
    echo "Ensuring Apple Silicon compatible NDK is installed..."
    if command -v sdkmanager >/dev/null 2>&1; then
        sdkmanager "ndk;24.0.8215888" --no_https
    else
        echo "WARNING: sdkmanager not found. Please ensure NDK 24.0.8215888 is installed."
    fi
    
    echo "Prerequisites verified."
}

# Patch gradle configuration for Java 17 compatibility
patch_gradle_config() {
    echo "Patching Gradle configuration for Java 17 compatibility..."
    
    # Read SDK version from metadata.json
    local sdk_version
    if [[ -f "../metadata.json" ]]; then
        sdk_version=$(grep -o '"sdk": *"[^"]*"' ../metadata.json | cut -d'"' -f4)
        echo "Using SDK version from metadata.json: $sdk_version"
    else
        sdk_version="33"  # fallback
        echo "WARNING: metadata.json not found, using fallback SDK version: $sdk_version"
    fi
    
    # Patch gradle-wrapper.properties to use compatible Gradle version for SDK 35
    if [[ -f "gradle/wrapper/gradle-wrapper.properties" ]]; then
        echo "Updating Gradle version to 8.13 for Java 21 compatibility..."
        sed -i '' 's|distributionUrl=.*|distributionUrl=https\\://services.gradle.org/distributions/gradle-8.13-bin.zip|' gradle/wrapper/gradle-wrapper.properties
    fi
    
    # Patch build.gradle to use compatible Android Gradle Plugin for Java 21
    if [[ -f "build.gradle" ]]; then
        echo "Updating Android Gradle Plugin to 8.9.3 for Java 21 compatibility..."
        sed -i '' 's|classpath.*gradle:.*|classpath '\''com.android.tools.build:gradle:8.9.3'\''|' build.gradle
    fi
    
    # Patch gradle.properties for Java 17 module access and SDK consistency
    if [[ -f "gradle.properties" ]]; then
        echo "Patching gradle.properties for Java 17 compatibility with SDK $sdk_version..."
        sed -i '' \
            -e 's|^org.gradle.jvmargs=.*|org.gradle.jvmargs=-Xmx2048M --add-opens=java.base/java.io=ALL-UNNAMED --add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.util=ALL-UNNAMED|' \
            -e "s|^targetSdkVersion=.*|targetSdkVersion=$sdk_version|" \
            -e "s|^compileSdkVersion=.*|compileSdkVersion=$sdk_version|" \
            -e 's|^ndkVersion=.*|ndkVersion=24.0.8215888|' \
            gradle.properties
    fi
    
    # Patch AndroidManifest.xml to add missing android:exported attributes for SDK 31+
    if [[ -f "app/src/main/AndroidManifest.xml" ]]; then
        echo "Patching AndroidManifest.xml to add android:exported attributes..."
        
        # Remove any existing android:exported attributes to avoid duplicates
        echo "Removing any existing android:exported attributes to avoid duplicates..."
        sed -i '' '/android:exported=/d' app/src/main/AndroidManifest.xml
        
        # Add android:exported="true" to TermuxActivity (.app.TermuxActivity)
        sed -i '' 's|android:name="\.app\.TermuxActivity"|android:name=".app.TermuxActivity"\n            android:exported="true"|' app/src/main/AndroidManifest.xml
        
        # Add android:exported="true" to TermuxFileReceiverActivity (.filepicker.TermuxFileReceiverActivity)
        sed -i '' 's|android:name="\.filepicker\.TermuxFileReceiverActivity"|android:name=".filepicker.TermuxFileReceiverActivity"\n            android:exported="true"|' app/src/main/AndroidManifest.xml
    fi
    
    # Patch Java source code to fix deprecated API calls for SDK 33+
    if [[ -f "app/src/main/java/com/termux/app/activities/HelpActivity.java" ]]; then
        echo "Patching HelpActivity.java to remove deprecated setAppCacheEnabled() call..."
        # Remove the deprecated setAppCacheEnabled() call
        sed -i '' '/settings\.setAppCacheEnabled(false);/d' app/src/main/java/com/termux/app/activities/HelpActivity.java
    fi
    
    # Patch NDK version for Apple Silicon compatibility and add namespace for AGP 8.0+
    if [[ -f "app/build.gradle" ]]; then
        echo "Patching app/build.gradle to use Apple Silicon compatible NDK version and add namespace..."
        # Update NDK version to one that supports Apple Silicon (NDK r25+)
        sed -i '' 's|ndkVersion = System.getenv("JITPACK_NDK_VERSION") ?: project.properties.ndkVersion|ndkVersion = "24.0.8215888"|' app/build.gradle
        
        # Add namespace for AGP 8.0+ compatibility (required when using AGP 8.0+)
        if ! grep -q "namespace" app/build.gradle; then
            echo "Adding namespace to app/build.gradle for AGP 8.0+ compatibility..."
            # Find the android block and add namespace after it
            sed -i '' '/^android {/a\
    namespace '\''com.termux'\''
' app/build.gradle
        fi
    fi
    
    # Remove any ndk.dir override in local.properties that might force old NDK
    if [[ -f "local.properties" ]]; then
        echo "Removing ndk.dir override from local.properties..."
        sed -i '' '/^ndk\.dir=/d' local.properties
    fi
    
    # Patch AndroidManifest.xml to add android:exported attributes
    if [[ -f "app/src/main/AndroidManifest.xml" ]]; then
        echo "Patching AndroidManifest.xml to add android:exported attributes..."
        
        # Restore original file first to avoid any corruption
        echo "Restoring original AndroidManifest.xml to avoid corruption..."
        git checkout HEAD -- app/src/main/AndroidManifest.xml
        
        # Add android:exported="true" to TermuxActivity (.app.TermuxActivity) - more precise matching
        if grep -q 'android:name="\.app\.TermuxActivity"' app/src/main/AndroidManifest.xml; then
            echo "Adding android:exported to TermuxActivity..."
            sed -i '' '/android:name="\.app\.TermuxActivity"/a\
            android:exported="true"' app/src/main/AndroidManifest.xml
        fi
        
        # Add android:exported="true" to TermuxFileReceiverActivity (.filepicker.TermuxFileReceiverActivity) - more precise matching
        if grep -q 'android:name="\.filepicker\.TermuxFileReceiverActivity"' app/src/main/AndroidManifest.xml; then
            echo "Adding android:exported to TermuxFileReceiverActivity..."
            sed -i '' '/android:name="\.filepicker\.TermuxFileReceiverActivity"/a\
            android:exported="true"' app/src/main/AndroidManifest.xml
        fi
        
        # Add android:exported="true" to HomeActivity (activity-alias with intent filter)
        if grep -q 'android:name="\.HomeActivity"' app/src/main/AndroidManifest.xml; then
            echo "Adding android:exported to HomeActivity..."
            sed -i '' '/android:name="\.HomeActivity"/a\
            android:exported="true"' app/src/main/AndroidManifest.xml
        fi
        
        # Add android:foregroundServiceType to TermuxService for Android 14+ (SDK 34+)
        if grep -q 'android:name="\.app\.TermuxService"' app/src/main/AndroidManifest.xml; then
            echo "Adding android:foregroundServiceType to TermuxService..."
            sed -i '' '/android:name="\.app\.TermuxService"/a\
            android:foregroundServiceType="dataSync"' app/src/main/AndroidManifest.xml
        fi
        
        # Add FOREGROUND_SERVICE_DATA_SYNC permission for Android 14+ (SDK 34+)
        if ! grep -q 'android.permission.FOREGROUND_SERVICE_DATA_SYNC' app/src/main/AndroidManifest.xml; then
            echo "Adding FOREGROUND_SERVICE_DATA_SYNC permission..."
            sed -i '' '/<uses-permission android:name="android.permission.FOREGROUND_SERVICE" \/>/a\
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_DATA_SYNC" \/>' app/src/main/AndroidManifest.xml
        fi
    fi
    
    # Patch HelpActivity.java to remove deprecated setAppCacheEnabled() call
    if [[ -f "app/src/main/java/com/termux/app/activities/HelpActivity.java" ]]; then
        echo "Patching HelpActivity.java to remove deprecated setAppCacheEnabled() call..."
        sed -i '' '/settings\.setAppCacheEnabled(false);/d' app/src/main/java/com/termux/app/activities/HelpActivity.java
    fi
    
    # Fix missing AppCompat style reference in termux-shared
    if [[ -f "termux-shared/src/main/java/com/termux/shared/interact/MessageDialogUtils.java" ]]; then
        echo "Fixing missing AppCompat style reference in MessageDialogUtils.java..."
        # First restore the original file to avoid multiple replacements
        git checkout HEAD -- termux-shared/src/main/java/com/termux/shared/interact/MessageDialogUtils.java
        # Replace the problematic style reference with the default theme (simpler approach)
        sed -i '' 's/R\.style\.Theme_AppCompat_Light_Dialog/0/' termux-shared/src/main/java/com/termux/shared/interact/MessageDialogUtils.java
    fi
    
    # Fix PendingIntent mutability flags for Android 12+ (SDK 31+)
    if [[ -f "app/src/main/java/com/termux/app/TermuxService.java" ]]; then
        echo "Fixing PendingIntent mutability flags in TermuxService for Android 12+..."
        # Replace PendingIntent.getActivity(this, 0, notificationIntent, 0) with FLAG_IMMUTABLE
        sed -i '' 's/PendingIntent\.getActivity(this, 0, notificationIntent, 0)/PendingIntent.getActivity(this, 0, notificationIntent, PendingIntent.FLAG_IMMUTABLE)/' app/src/main/java/com/termux/app/TermuxService.java
        
        # Replace PendingIntent.getService(this, 0, exitIntent, 0) with FLAG_IMMUTABLE
        sed -i '' 's/PendingIntent\.getService(this, 0, exitIntent, 0)/PendingIntent.getService(this, 0, exitIntent, PendingIntent.FLAG_IMMUTABLE)/' app/src/main/java/com/termux/app/TermuxService.java
        
        # Replace PendingIntent.getService(this, 0, toggleWakeLockIntent, 0) with FLAG_IMMUTABLE
        sed -i '' 's/PendingIntent\.getService(this, 0, toggleWakeLockIntent, 0)/PendingIntent.getService(this, 0, toggleWakeLockIntent, PendingIntent.FLAG_IMMUTABLE)/' app/src/main/java/com/termux/app/TermuxService.java
    fi
    
    # Fix PendingIntent mutability flags in CrashUtils for Android 12+ (SDK 31+)
    if [[ -f "app/src/main/java/com/termux/app/utils/CrashUtils.java" ]]; then
        echo "Fixing PendingIntent mutability flags in CrashUtils for Android 12+..."
        # Replace PendingIntent.getActivity(context, 0, notificationIntent, PendingIntent.FLAG_UPDATE_CURRENT) with FLAG_IMMUTABLE
        sed -i '' 's/PendingIntent\.getActivity(context, 0, notificationIntent, PendingIntent\.FLAG_UPDATE_CURRENT)/PendingIntent.getActivity(context, 0, notificationIntent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE)/' app/src/main/java/com/termux/app/utils/CrashUtils.java
        # Also fix any other PendingIntent.getActivity calls without flags
        sed -i '' 's/PendingIntent\.getActivity(context, 0, notificationIntent, 0)/PendingIntent.getActivity(context, 0, notificationIntent, PendingIntent.FLAG_IMMUTABLE)/' app/src/main/java/com/termux/app/utils/CrashUtils.java
    fi
    
    # Fix BroadcastReceiver registration for Android 12+ (SDK 31+)
    if [[ -f "app/src/main/java/com/termux/app/TermuxActivity.java" ]]; then
        echo "Fixing BroadcastReceiver registration for Android 12+..."
        # Replace registerReceiver(mTermuxActivityBroadcastReceiver, intentFilter) with RECEIVER_NOT_EXPORTED
        sed -i '' 's/registerReceiver(mTermuxActivityBroadcastReceiver, intentFilter)/registerReceiver(mTermuxActivityBroadcastReceiver, intentFilter, Context.RECEIVER_NOT_EXPORTED)/' app/src/main/java/com/termux/app/TermuxActivity.java
    fi
    
    # Fix missing drawable reference in app module
    echo "Fixing missing drawable references in app module..."
    for java_file in app/src/main/java/com/termux/app/utils/PluginUtils.java app/src/main/java/com/termux/app/utils/CrashUtils.java; do
        if [[ -f "$java_file" ]]; then
            echo "Fixing drawable reference in $java_file..."
            # First restore the original file to avoid multiple replacements
            git checkout HEAD -- "$java_file"
            # Replace R.drawable.ic_error_notification with com.termux.shared.R.drawable.ic_error_notification
            sed -i '' 's/R\.drawable\.ic_error_notification/com.termux.shared.R.drawable.ic_error_notification/' "$java_file"
        fi
    done
    
    # Add namespaces to all library modules for AGP 8.0+ compatibility
    echo "Adding namespaces to all library modules for AGP 8.0+ compatibility..."
    
    # Add namespace to terminal-emulator
    if [[ -f "terminal-emulator/build.gradle" ]] && ! grep -q "namespace" terminal-emulator/build.gradle; then
        echo "Adding namespace 'com.termux.terminal' to terminal-emulator/build.gradle..."
        sed -i '' "/^android {/a\\
    namespace 'com.termux.terminal'
" terminal-emulator/build.gradle
    fi
    
    # Add namespace to termux-shared
    if [[ -f "termux-shared/build.gradle" ]] && ! grep -q "namespace" termux-shared/build.gradle; then
        echo "Adding namespace 'com.termux.shared' to termux-shared/build.gradle..."
        sed -i '' "/^android {/a\\
    namespace 'com.termux.shared'
" termux-shared/build.gradle
    fi
    
    # Add namespace to terminal-view
    if [[ -f "terminal-view/build.gradle" ]] && ! grep -q "namespace" terminal-view/build.gradle; then
        echo "Adding namespace 'com.termux.view' to terminal-view/build.gradle..."
        sed -i '' "/^android {/a\\
    namespace 'com.termux.view'
" terminal-view/build.gradle
    fi
    
    # Fix deprecated classifier() method for Gradle 8.0+ compatibility
    echo "Fixing deprecated classifier() method in all build.gradle files for Gradle 8.0+..."
    for build_file in terminal-emulator/build.gradle termux-shared/build.gradle terminal-view/build.gradle; do
        if [[ -f "$build_file" ]]; then
            echo "Fixing $build_file..."
            if grep -q 'classifier "sources"' "$build_file"; then
                echo "Found classifier in $build_file, replacing..."
                sed -i '' 's|classifier "sources"|archiveClassifier.set("sources")|' "$build_file"
                echo "Replacement completed for $build_file"
            else
                echo "No classifier found in $build_file"
            fi
        else
            echo "File $build_file not found"
        fi
    done
    
    # Fix AGP 8.0+ publishing configuration issues
    echo "Fixing AGP 8.0+ publishing configuration issues..."
    for build_file in terminal-emulator/build.gradle termux-shared/build.gradle terminal-view/build.gradle; do
        if [[ -f "$build_file" ]]; then
            echo "Removing problematic publishing block from $build_file..."
            # Remove the entire afterEvaluate block that contains publishing
            sed -i '' '/^afterEvaluate {/,/^}$/d' "$build_file"
            echo "Publishing block removed from $build_file"
        fi
    done
    
    # Remove package attributes from library module manifests (AGP 8.0+ warning)
    echo "Removing package attributes from library module manifests for AGP 8.0+ compatibility..."
    for manifest_file in terminal-emulator/src/main/AndroidManifest.xml termux-shared/src/main/AndroidManifest.xml terminal-view/src/main/AndroidManifest.xml; do
        if [[ -f "$manifest_file" ]]; then
            echo "Removing package attribute from $manifest_file..."
            sed -i '' 's/ package="[^"]*"//' "$manifest_file"
        fi
    done
    
    # Remove any hard-coded ABI filters to allow dynamic ABI selection
    echo "Removing hard-coded ABI filters to allow dynamic selection..."
    if grep -q "abiFilters" app/build.gradle; then
        # Remove any existing abiFilters
        sed -i '' '/abiFilters/d' app/build.gradle
    fi
    
    # Add packaging options to fix native library extraction
    echo "Adding packaging options for native library compatibility..."
    if ! grep -q "packagingOptions" app/build.gradle; then
        # Add packagingOptions to the android block
        sed -i '' '/^android {/a\
    packagingOptions {\
        jniLibs {\
            useLegacyPackaging = true\
        }\
    }\
' app/build.gradle
    fi
    
}

# Make gradle wrapper executable
chmod +x gradlew

# Check prerequisites
check_prerequisites

# Apply patches for Java 17 compatibility
patch_gradle_config

# Clean everything and rebuild
echo "Cleaning build cache and rebuilding..."
./gradlew --stop
./gradlew clean

# Download bootstrap files (required for NDK build)
echo "Downloading bootstrap files..."
./gradlew downloadBootstraps --no-daemon

# Build APKs for all architectures (splits + universal)
echo "Building APKs for all architectures..."
if ! ./gradlew assembleRelease --no-daemon; then
    echo "ERROR: Gradle build failed"
    exit 1
fi

# Select the universal APK (CI infrastructure handles device management)
echo "Selecting universal APK..."
UNIVERSAL_APK=$(find . -path "*/build/outputs/apk/release/*universal*release*.apk" -type f | head -n1)
if [ -n "$UNIVERSAL_APK" ]; then
    APK="$UNIVERSAL_APK"
    echo "Using universal APK: $(basename "$APK")"
else
    # Fallback: any release APK
    APK=$(find . -path "*/build/outputs/apk/release/*.apk" -type f | head -n1)
    if [ -z "$APK" ]; then
        echo "ERROR: No APK produced"
        exit 1
    fi
    echo "Using fallback APK: $(basename "$APK")"
fi

# Sign the APK with debug keystore
sign_apk() {
    local apk_path="$1"
    echo "Signing APK with debug keystore..."
    
    # Use the existing dev_keystore.jks from the app directory
    KEYSTORE_FILE="app/dev_keystore.jks"
    
    if [[ ! -f "$KEYSTORE_FILE" ]]; then
        echo "ERROR: Keystore file not found at $KEYSTORE_FILE"
        return 1
    fi
    
    # Use apksigner 
    if [[ -z "$ANDROID_HOME" ]]; then
        echo "ERROR: ANDROID_HOME not set, cannot find apksigner"
        return 1
    fi
    
    APKSIGNER="$ANDROID_HOME/build-tools/*/apksigner"
    APKSIGNER=$(ls $APKSIGNER 2>/dev/null | head -1)
    
    if [[ ! -f "$APKSIGNER" ]]; then
        echo "WARNING: apksigner not found, falling back to jarsigner"
        jarsigner -verbose -sigalg SHA256withRSA -digestalg SHA256 -keystore "$KEYSTORE_FILE" -storepass xrj45yWGLbsO7W0v -keypass xrj45yWGLbsO7W0v "$apk_path" alias
    else
        echo "Using apksigner: $APKSIGNER"
        "$APKSIGNER" sign --ks "$KEYSTORE_FILE" --ks-key-alias alias --ks-pass pass:xrj45yWGLbsO7W0v --key-pass pass:xrj45yWGLbsO7W0v --v2-signing-enabled true "$apk_path"
    fi
    
    # Rename signed APK (remove -unsigned suffix if present)
    if echo "$apk_path" | grep -q "unsigned"; then
        APK_SIGNED="${apk_path/-unsigned.apk/.apk}"
        mv "$apk_path" "$APK_SIGNED"
        APK="$APK_SIGNED"
        echo "Renamed signed APK to: $(basename "$APK")"
    fi
    
    echo "APK signed successfully"
}

# Sign the APK
sign_apk "$APK"

mkdir -p ../apk
cp "$APK" ../apk/termux-release.apk
echo "APK built successfully: apk/termux-release.apk"
echo "APK size: $(du -h ../apk/termux-release.apk | cut -f1)"
echo "APK type: $(basename "$APK")"

cd ..

echo "Source code setup completed"
