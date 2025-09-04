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
        echo "Updating Gradle version to 8.0 for SDK 35 compatibility..."
        sed -i.bak 's|distributionUrl=.*|distributionUrl=https\\://services.gradle.org/distributions/gradle-8.0-all.zip|' gradle/wrapper/gradle-wrapper.properties
    fi
    
    # Patch build.gradle to use compatible Android Gradle Plugin for SDK 35
    if [[ -f "build.gradle" ]]; then
        echo "Updating Android Gradle Plugin to 8.0.2 for SDK 35 compatibility..."
        sed -i.bak 's|classpath.*gradle:.*|classpath '\''com.android.tools.build:gradle:8.0.2'\''|' build.gradle
    fi
    
    # Patch gradle.properties for Java 17 module access and SDK consistency
    if [[ -f "gradle.properties" ]]; then
        echo "Patching gradle.properties for Java 17 compatibility with SDK $sdk_version..."
        sed -i.bak \
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
        sed -i.bak '/android:exported=/d' app/src/main/AndroidManifest.xml
        
        # Add android:exported="true" to TermuxActivity (.app.TermuxActivity)
        sed -i.bak 's|android:name="\.app\.TermuxActivity"|android:name=".app.TermuxActivity"\n            android:exported="true"|' app/src/main/AndroidManifest.xml
        
        # Add android:exported="true" to TermuxFileReceiverActivity (.filepicker.TermuxFileReceiverActivity)
        sed -i.bak 's|android:name="\.filepicker\.TermuxFileReceiverActivity"|android:name=".filepicker.TermuxFileReceiverActivity"\n            android:exported="true"|' app/src/main/AndroidManifest.xml
    fi
    
    # Patch Java source code to fix deprecated API calls for SDK 33+
    if [[ -f "app/src/main/java/com/termux/app/activities/HelpActivity.java" ]]; then
        echo "Patching HelpActivity.java to remove deprecated setAppCacheEnabled() call..."
        # Remove the deprecated setAppCacheEnabled() call
        sed -i.bak '/settings\.setAppCacheEnabled(false);/d' app/src/main/java/com/termux/app/activities/HelpActivity.java
    fi
    
    # Patch NDK version for Apple Silicon compatibility and add namespace for AGP 8.0+
    if [[ -f "app/build.gradle" ]]; then
        echo "Patching app/build.gradle to use Apple Silicon compatible NDK version and add namespace..."
        # Update NDK version to one that supports Apple Silicon (NDK r25+)
        sed -i.bak 's|ndkVersion = System.getenv("JITPACK_NDK_VERSION") ?: project.properties.ndkVersion|ndkVersion = "24.0.8215888"|' app/build.gradle
        
        # Add namespace for AGP 8.0+ compatibility (required when using AGP 8.0+)
        if ! grep -q "namespace" app/build.gradle; then
            echo "Adding namespace to app/build.gradle for AGP 8.0+ compatibility..."
            # Find the android block and add namespace after it
            sed -i.bak '/^android {/a\
    namespace '\''com.termux'\''
' app/build.gradle
        fi
    fi
    
    # Remove any ndk.dir override in local.properties that might force old NDK
    if [[ -f "local.properties" ]]; then
        echo "Removing ndk.dir override from local.properties..."
        sed -i.bak '/^ndk\.dir=/d' local.properties
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
            sed -i.bak '/android:name="\.app\.TermuxActivity"/a\
            android:exported="true"' app/src/main/AndroidManifest.xml
        fi
        
        # Add android:exported="true" to TermuxFileReceiverActivity (.filepicker.TermuxFileReceiverActivity) - more precise matching
        if grep -q 'android:name="\.filepicker\.TermuxFileReceiverActivity"' app/src/main/AndroidManifest.xml; then
            echo "Adding android:exported to TermuxFileReceiverActivity..."
            sed -i.bak '/android:name="\.filepicker\.TermuxFileReceiverActivity"/a\
            android:exported="true"' app/src/main/AndroidManifest.xml
        fi
        
        # Add android:exported="true" to HomeActivity (activity-alias with intent filter)
        if grep -q 'android:name="\.HomeActivity"' app/src/main/AndroidManifest.xml; then
            echo "Adding android:exported to HomeActivity..."
            sed -i.bak '/android:name="\.HomeActivity"/a\
            android:exported="true"' app/src/main/AndroidManifest.xml
        fi
    fi
    
    # Patch HelpActivity.java to remove deprecated setAppCacheEnabled() call
    if [[ -f "app/src/main/java/com/termux/app/activities/HelpActivity.java" ]]; then
        echo "Patching HelpActivity.java to remove deprecated setAppCacheEnabled() call..."
        sed -i.bak '/settings\.setAppCacheEnabled(false);/d' app/src/main/java/com/termux/app/activities/HelpActivity.java
    fi
    
    # Fix missing AppCompat style reference in termux-shared
    if [[ -f "termux-shared/src/main/java/com/termux/shared/interact/MessageDialogUtils.java" ]]; then
        echo "Fixing missing AppCompat style reference in MessageDialogUtils.java..."
        # First restore the original file to avoid multiple replacements
        git checkout HEAD -- termux-shared/src/main/java/com/termux/shared/interact/MessageDialogUtils.java
        # Replace the problematic style reference with the default theme (simpler approach)
        sed -i.bak 's/R\.style\.Theme_AppCompat_Light_Dialog/0/' termux-shared/src/main/java/com/termux/shared/interact/MessageDialogUtils.java
    fi
    
    # Fix missing drawable reference in app module
    echo "Fixing missing drawable references in app module..."
    for java_file in app/src/main/java/com/termux/app/utils/PluginUtils.java app/src/main/java/com/termux/app/utils/CrashUtils.java; do
        if [[ -f "$java_file" ]]; then
            echo "Fixing drawable reference in $java_file..."
            # First restore the original file to avoid multiple replacements
            git checkout HEAD -- "$java_file"
            # Replace R.drawable.ic_error_notification with com.termux.shared.R.drawable.ic_error_notification
            sed -i.bak 's/R\.drawable\.ic_error_notification/com.termux.shared.R.drawable.ic_error_notification/' "$java_file"
        fi
    done
    
    # Add namespaces to all library modules for AGP 8.0+ compatibility
    echo "Adding namespaces to all library modules for AGP 8.0+ compatibility..."
    
    # Add namespace to terminal-emulator
    if [[ -f "terminal-emulator/build.gradle" ]] && ! grep -q "namespace" terminal-emulator/build.gradle; then
        echo "Adding namespace 'com.termux.terminal' to terminal-emulator/build.gradle..."
        sed -i.bak "/^android {/a\\
    namespace 'com.termux.terminal'
" terminal-emulator/build.gradle
    fi
    
    # Add namespace to termux-shared
    if [[ -f "termux-shared/build.gradle" ]] && ! grep -q "namespace" termux-shared/build.gradle; then
        echo "Adding namespace 'com.termux.shared' to termux-shared/build.gradle..."
        sed -i.bak "/^android {/a\\
    namespace 'com.termux.shared'
" termux-shared/build.gradle
    fi
    
    # Add namespace to terminal-view
    if [[ -f "terminal-view/build.gradle" ]] && ! grep -q "namespace" terminal-view/build.gradle; then
        echo "Adding namespace 'com.termux.view' to terminal-view/build.gradle..."
        sed -i.bak "/^android {/a\\
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
                sed -i.bak 's|classifier "sources"|archiveClassifier.set("sources")|' "$build_file"
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
            sed -i.bak '/^afterEvaluate {/,/^}$/d' "$build_file"
            echo "Publishing block removed from $build_file"
        fi
    done
    
    # Remove package attributes from library module manifests (AGP 8.0+ warning)
    echo "Removing package attributes from library module manifests for AGP 8.0+ compatibility..."
    for manifest_file in terminal-emulator/src/main/AndroidManifest.xml termux-shared/src/main/AndroidManifest.xml terminal-view/src/main/AndroidManifest.xml; do
        if [[ -f "$manifest_file" ]]; then
            echo "Removing package attribute from $manifest_file..."
            sed -i.bak 's/ package="[^"]*"//' "$manifest_file"
        fi
    done
    
    # Add ABI filter to build only for arm64-v8a (matches emulator)
    echo "Adding ABI filter for arm64-v8a compatibility..."
    if ! grep -q "abiFilters" app/build.gradle; then
        # Add abiFilters to the defaultConfig block
        sed -i.bak '/defaultConfig {/a\
        ndk {\
            abiFilters "arm64-v8a"\
        }\
' app/build.gradle
    fi
    
    # Fix splits configuration to only include arm64-v8a
    echo "Fixing splits configuration for arm64-v8a only..."
    if grep -q "include 'x86', 'x86_64', 'armeabi-v7a', 'arm64-v8a'" app/build.gradle; then
        sed -i.bak "s/include 'x86', 'x86_64', 'armeabi-v7a', 'arm64-v8a'/include 'arm64-v8a'/" app/build.gradle
    fi
    
    # Add packaging options to fix native library extraction
    echo "Adding packaging options for native library compatibility..."
    if ! grep -q "packagingOptions" app/build.gradle; then
        # Add packagingOptions to the android block
        sed -i.bak '/^android {/a\
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
# rm -rf ~/.gradle/caches ~/.gradle/daemon
./gradlew clean

# Build APK using host environment (like other apps)
echo "Building APK using host environment..."
if ! ./gradlew assembleDebug --no-daemon --max-workers=1; then
    echo "ERROR: Gradle build failed"
    exit 1
fi

# Find and copy APK
APK=$(find . -path "*/build/outputs/apk/debug/*.apk" -type f | head -n1)
if [ -z "$APK" ]; then
    echo "ERROR: No APK produced"
    exit 1
fi

cp "$APK" ../termux-debug.apk
echo "APK built successfully: termux-debug.apk"
echo "APK size: $(du -h ../termux-debug.apk | cut -f1)"

cd ..

echo "Source code setup completed"
