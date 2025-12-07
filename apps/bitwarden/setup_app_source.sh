#!/bin/bash
set -e

BITWARDEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_VARIANT="assembleFdroidDebug"
CACHED_APK="$BITWARDEN_DIR/bitwarden.apk"

CODEBASE_DIR="$BITWARDEN_DIR/codebase"
FDROID_DEBUG_APK_DIR="$CODEBASE_DIR/app/build/outputs/apk/fdroid/debug"

# Resolved APK path (absolute). Will be filled by resolve_apk_path()
APK_PATH=""

create_user_properties() {
    # Create user.properties if missing (Bitwarden specific)
    USER_PROPERTIES="$BITWARDEN_DIR/codebase/user.properties"
    if [ ! -f "$USER_PROPERTIES" ]; then
        echo "[INFO] Creating user.properties in codebase/"
        if [ -z "$GH_TOKEN" ]; then
            read -p "Enter your GitHub Personal Access Token (with read:packages scope): " GH_TOKEN
        else
            echo "[INFO] Using GH_TOKEN from environment."
        fi
        echo "gitHubToken=$GH_TOKEN" > "$USER_PROPERTIES"
        echo "localSdk=false" >> "$USER_PROPERTIES"
        echo "[INFO] user.properties created."
    else
        echo "[INFO] user.properties already exists."
    fi
}

# Build Bitwarden APK with optimal settings for CI with an emulator
build_bitwarden() {
    echo "Building Bitwarden..."
    
    echo "Gradle settings: $GRADLE_OPTS"
    ./gradlew :app:$BUILD_VARIANT --console=plain -S
    
    echo "Build completed successfully."
}

# Resolve latest APK path across common output folders
resolve_apk_path() {
    # Priority 1: Check for the latest APK in the Gradle build output directory.
    # Use compgen to safely check for files matching the glob pattern.
    if compgen -G "$FDROID_DEBUG_APK_DIR/*.apk" > /dev/null; then
        # If files exist, find the newest one.
        local latest_build_apk
        latest_build_apk=$(ls -t "$FDROID_DEBUG_APK_DIR"/*.apk | head -n1)
        if [ -f "$latest_build_apk" ]; then
            APK_PATH="$latest_build_apk"
            return
        fi
    fi

    # Priority 2: Check for the cached APK in the app's root directory.
    if [ -f "$CACHED_APK" ]; then
        APK_PATH="$CACHED_APK"
        return
    fi
    
    # If no APK is found, ensure the path is empty.
    APK_PATH=""
}

copy_to_project_root() {
    echo "Copying Gradle-built APK to project root..."
    cp "$APK_PATH" "$CACHED_APK"
    cp "$APK_PATH" "$BITWARDEN_DIR/bitwarden.apk"
    echo "APK copied to project root and bitwarden.apk."
}

copy_to_apk_dir() {
    mkdir -p "$BITWARDEN_DIR/apk"
    cp "$APK_PATH" "$BITWARDEN_DIR/apk/bitwarden.apk"
    cp "$APK_PATH" "$FDROID_DEBUG_APK_DIR/com.x8bit.bitwarden.dev-fdroid.apk"
    echo "APK copied to apps/bitwarden/apk/bitwarden.apk and fdroid debug output."
}

# Main function with robust logic
main() {
    echo "=== RUNNING setup_app_source.sh ==="

    # Bitwarden specific: create user.properties if missing
    create_user_properties

    cd "$CODEBASE_DIR"

    # Try to resolve a prebuilt APK first
    resolve_apk_path
    
    # If no prebuilt APK is found, build it
    if [ -n "$APK_PATH" ]; then
        echo "[INFO] Prebuilt APK found at: $APK_PATH. Skipping build."
    else
        echo "[INFO] No prebuilt APK found. Building now..."
        build_bitwarden
        resolve_apk_path  # Re-resolve after build -> Gradle build output directory
    fi

    # Verify the APK exists before finishing, otherwise exit.
    if [ -z "$APK_PATH" ]; then
        echo "[FATAL ERROR] APK file not found at the expected path."
        exit 1
    fi

    # If the found APK is not the cached one, copy it to the cache location.
    if [ "$APK_PATH" != "$CACHED_APK" ]; then
        copy_to_project_root
        copy_to_apk_dir
    fi
    
    echo ""
    echo "Bitwarden build completed successfully!"
    echo === FINISHED setup_app_source.sh ===
}

main