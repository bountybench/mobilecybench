#!/bin/bash
set -e

BITWARDEN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CACHED_APK_NAME="bitwarden.apk"

CODEBASE_DIR="$BITWARDEN_DIR/codebase"
FDROID_DEBUG_APK_DIR="$CODEBASE_DIR/app/build/outputs/apk/fdroid/debug"

# Resolved APK path (absolute). Will be filled by resolve_apk_path()
APK_PATH=""

create_user_properties() {
    # Create user.properties if missing (Bitwarden specific)
    USER_PROPERTIES="$BITWARDEN_DIR/codebase/user.properties"
    if [ ! -f "$USER_PROPERTIES" ]; then
        echo "[INFO] Creating user.properties in codebase/"
        if [ -z "$GITHUB_TOKEN" ]; then
            read -p "Enter your GitHub Personal Access Token (with read:packages scope): " GITHUB_TOKEN
        else
            echo "[INFO] Using GITHUB_TOKEN from environment."
        fi
        echo "gitHubToken=$GITHUB_TOKEN" > "$USER_PROPERTIES"
        echo "localSdk=false" >> "$USER_PROPERTIES"
        echo "[INFO] user.properties created."
    else
        echo "[INFO] user.properties already exists."
    fi
}

# Build Bitwarden APK with optimal settings for CI with an emulator
build_bitwarden() {
    echo "Building Bitwarden (Optimized for CI with Emulator)..."
    
    echo "Gradle settings: $GRADLE_OPTS"
    ./gradlew :app:assembleFdroidDebug --console=plain -S
    
    echo "Build completed successfully."
}

# Resolve latest APK path across common output folders
resolve_apk_path() {
    local candidates=()
    # Prefer cached prebuilt APK copied by CI (outside submodule)
    if [ -f "$BITWARDEN_DIR/$CACHED_APK_NAME" ]; then
        candidates+=( "$BITWARDEN_DIR/$CACHED_APK_NAME" )
    fi
    if compgen -G "$FDROID_DEBUG_APK_DIR/*.apk" > /dev/null; then
        candidates+=( $(ls -t "$FDROID_DEBUG_APK_DIR"/*.apk 2>/dev/null) )
    fi

    if [ ${#candidates[@]} -gt 0 ]; then
        APK_PATH="${candidates[0]}"
    else
        APK_PATH=""
    fi
}

copy_to_project_root() {
    echo "Copying Gradle-built APK to project root..."
    cp "$APK_PATH" "$BITWARDEN_DIR/$CACHED_APK_NAME"
    echo "APK copied to project root."
}

# Main function with robust logic
main() {
    echo "=== RUNNING build_app.sh ==="

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
        resolve_apk_path  # Re-resolve after build
    fi

    # Verify the APK exists
    if [[ ! -f "$APK_PATH" ]]; then
        echo "[FATAL ERROR] APK file not found at the expected path."
        exit 1
    fi
    
    # Copy the APK to the project root
    copy_to_project_root
    
    echo ""
    echo "Bitwarden build completed successfully!"
    echo "Gradle-built APK file path: $APK_PATH"
    echo "Cached APK file path: $BITWARDEN_DIR/$CACHED_APK_NAME"
    echo === FINISHED build_app.sh ===
}

# Run main function
main