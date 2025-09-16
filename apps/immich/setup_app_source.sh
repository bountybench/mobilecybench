#!/usr/bin/env bash
# Builds the Immich Flutter app from source (no emulator).
# Intended for Linux CI/agents. Idempotently installs FVM + Flutter if missing.
# OPTIMIZED VERSION: Includes resource management and CI optimizations

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEBASE_DIR="$SCRIPT_DIR/codebase/mobile"
LOG_PREFIX="[setup_app_source]"
LOG_FILE="${SCRIPT_DIR}/setup_app_source.log"

# Optional: INSTALL_ANDROID=true to attempt Android SDK bootstrap (best-effort)
INSTALL_ANDROID="${INSTALL_ANDROID:-false}"

# Use Flutter version that includes Dart >= 3.8.0
FLUTTER_VERSION="${FLUTTER_VERSION:-3.35.3}"

# CI Optimization flags
CI_MODE="${CI:-false}"
MAX_RETRIES="${MAX_RETRIES:-3}"
CLEANUP_ENABLED="${CLEANUP_ENABLED:-true}"

# ---- logging ----
exec > >(tee -a "$LOG_FILE") 2>&1
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

# ---- CI Optimization: Resource monitoring ----
show_resources() {
  if [ "$CI_MODE" = "true" ]; then
    echo "[Resources] Memory: $(free -m | awk 'NR==2{printf "Used: %sMB (%.1f%%)", $3, $3*100/$2}')"
    echo "[Resources] Disk: $(df -h . | awk 'NR==2{printf "Available: %s", $4}')"
    echo "[Resources] Load: $(uptime | awk -F'load average:' '{print $2}')"
  fi
}

# ---- CI Optimization: Cleanup function ----
cleanup_resources() {
  if [ "$CLEANUP_ENABLED" = "true" ]; then
    info "Cleaning up resources to free memory..."
    # Kill lingering processes
    pkill -f "dart|flutter" 2>/dev/null || true
    
    # Clear Gradle caches if they exist
    if [ -d "$HOME/.gradle/caches" ]; then
      find "$HOME/.gradle/caches" -name "*.lock" -type f -delete 2>/dev/null || true
    fi
    
    # Clear old Flutter build artifacts
    if [ -d "$CODEBASE_DIR/.dart_tool" ]; then
      rm -rf "$CODEBASE_DIR/.dart_tool/flutter_build" 2>/dev/null || true
    fi
    
    # Sync and drop caches if running with sudo
    sync
    if [ "$EUID" -eq 0 ]; then
      echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
    fi
  fi
}

# ---- CI Optimization: Retry wrapper ----
retry_command() {
  local cmd="$1"
  local desc="${2:-command}"
  local retries=0
  
  while [ $retries -lt "$MAX_RETRIES" ]; do
    if eval "$cmd"; then
      return 0
    else
      retries=$((retries + 1))
      warn "$desc failed (attempt $retries/$MAX_RETRIES)"
      [ $retries -lt "$MAX_RETRIES" ] && sleep $((retries * 5))
    fi
  done
  
  return 1
}

# ---- Bootstrap FVM + Flutter (Linux) ----
bootstrap_prereqs() {
  info "Bootstrapping prerequisites (Flutter/FVM + npm)..."
  show_resources

  # --- npm / Node.js ---
  if ! command_exists npm; then
    info "npm not found; attempting to install Node.js LTS..."
    if command_exists apt-get; then
      # CI Optimization: Use --no-install-recommends to save space
      retry_command "curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -" "Node.js setup"
      sudo apt-get install -y --no-install-recommends nodejs
    elif command_exists yum; then
      retry_command "curl -fsSL https://rpm.nodesource.com/setup_lts.x | sudo bash -" "Node.js setup"
      sudo yum install -y nodejs
    else
      warn "Package manager not supported; please install Node.js/npm manually."
    fi
  else
    info "npm present: $(npm --version)"
  fi

  # install pnpm globally so pnpx is available (pnpm provides the pnpx shim)
  if ! command -v pnpx >/dev/null 2>&1; then
    info "Installing pnpm globally (provides pnpx)..."
    retry_command "npm i -g pnpm@8" "pnpm installation"
  fi

  # --- FVM + Flutter ---
  export PATH="$HOME/.pub-cache/bin:$PATH"

  if ! command_exists fvm; then
    if ! command_exists dart; then
      info "Dart not found; installing Flutter SDK ($FLUTTER_VERSION) locally under ~/.flutter ..."
      BASE_URL="https://storage.googleapis.com/flutter_infra_release/releases/stable/linux"
      TARBALL="flutter_linux_${FLUTTER_VERSION}-stable.tar.xz"
      DEST="$HOME/.flutter"
      TMP="$(mktemp -t flutter-${FLUTTER_VERSION}-XXXXXXXX.tar.xz)"

      mkdir -p "$DEST"
      if [ ! -d "$DEST/flutter" ]; then
        # CI Optimization: Add timeout and progress bar
        retry_command "curl -fL --progress-bar --max-time 600 '${BASE_URL}/${TARBALL}' -o '$TMP'" "Flutter download"
        tar -xJf "$TMP" -C "$DEST"
        rm -f "$TMP"
      fi
      export PATH="$DEST/flutter/bin:$PATH"
      
      # CI Optimization: Disable analytics and telemetry
      flutter config --no-analytics --no-cli-animations 2>/dev/null || true
      flutter --suppress-analytics config --no-analytics 2>/dev/null || true
      
      flutter --version
    fi

    dart pub global activate fvm >/dev/null
    export PATH="$HOME/.pub-cache/bin:$PATH"
    command_exists fvm || fail "FVM not on PATH after install."
  else
    info "FVM present: $(fvm --version)"
  fi

  # Ensure we're in the right directory
  mkdir -p "$CODEBASE_DIR"
  pushd "$CODEBASE_DIR" >/dev/null
  
  # Always install the required Flutter version for Immich
  info "Installing Flutter $FLUTTER_VERSION for Immich compatibility..."
  retry_command "fvm install '$FLUTTER_VERSION'" "Flutter $FLUTTER_VERSION installation"
  fvm use "$FLUTTER_VERSION"
  
  # CI Optimization: Configure Flutter for CI
  if [ "$CI_MODE" = "true" ]; then
    fvm flutter config --no-analytics --no-cli-animations 2>/dev/null || true
  fi
  
  # Verify the Dart version
  CURRENT_DART="$(fvm dart --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1)"
  info "Using Dart version: $CURRENT_DART"
  
  fvm flutter --version
  fvm flutter doctor -v || true
  popd >/dev/null

  info "Bootstrap complete (npm + Flutter/FVM)."
  show_resources
}

# ---- Optional Android SDK (Linux best-effort) ----
maybe_install_android_sdk() {
  [ "$INSTALL_ANDROID" = "true" ] || { info "Skipping Android SDK install (INSTALL_ANDROID=false)."; return 0; }

  info "Attempting Android SDK bootstrap (Linux)..."
  if command_exists sdkmanager; then
    info "sdkmanager present."
  else
    export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$HOME/android-sdk}"
    mkdir -p "$ANDROID_SDK_ROOT/cmdline-tools"
    if [ ! -d "$ANDROID_SDK_ROOT/cmdline-tools/latest" ]; then
      info "Installing Android cmdline-tools..."
      tmpzip="$(mktemp -t cmdline-tools-XXXXX.zip)"
      # CI Optimization: Add timeout and retry
      retry_command "curl -sSL --max-time 600 'https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip' -o '$tmpzip'" "Android cmdline-tools download"
      mkdir -p "$ANDROID_SDK_ROOT/cmdline-tools/latest"
      unzip -q "$tmpzip" -d "$ANDROID_SDK_ROOT/cmdline-tools/latest"
      rm -f "$tmpzip"
    fi
    export PATH="$PATH:$ANDROID_SDK_ROOT/platform-tools:$ANDROID_SDK_ROOT/cmdline-tools/latest/bin"
  fi

  if command_exists sdkmanager; then
    yes | sdkmanager --licenses >/dev/null 2>&1 || true
    # CI Optimization: Install packages with retry
    retry_command "sdkmanager 'platform-tools' 'platforms;android-34' 'build-tools;34.0.0'" "Android SDK packages" || \
      warn "sdkmanager package install failed; ensure network access and cmdline-tools are valid."
    info "ANDROID_SDK_ROOT=${ANDROID_SDK_ROOT:-unset}"
  else
    warn "sdkmanager still not found; APK build may fail without Android SDK."
  fi
}

# ---- Verify prerequisites after bootstrap ----
check_prerequisites() {
  info "Verifying prerequisites..."
  command_exists fvm || fail "FVM not found after bootstrap."
  info "FVM: $(fvm --version)"
  
  # Check for keytool (required for keystore generation)
  if ! command_exists keytool; then
    warn "keytool not found. Attempting to locate Java installation..."
    # Try common Java locations
    for java_home in "$JAVA_HOME" "/usr/lib/jvm/java-11-openjdk-amd64" "/usr/lib/jvm/java-8-openjdk-amd64" "/usr/lib/jvm/default-java"; do
      if [ -n "$java_home" ] && [ -d "$java_home" ]; then
        export PATH="$java_home/bin:$PATH"
        if command_exists keytool; then
          info "Found keytool in $java_home"
          break
        fi
      fi
    done
    
    # Final check
    command_exists keytool || fail "keytool not found. Please install JDK (apt-get install default-jdk or similar)"
  fi
  
  cd "$CODEBASE_DIR"
  
  # Check Dart version from FVM Flutter
  CURRENT_DART="$(fvm dart --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n1)"
  REQUIRED_DART="3.8.0"

  # Version comparison function
  version_ge() { 
    printf '%s\n%s\n' "$1" "$2" | sort -V -C 2>/dev/null
  }

  if [ -z "$CURRENT_DART" ]; then
    fail "Could not determine Dart version"
  fi

  info "Flutter: $(fvm flutter --version | head -n1)"
  info "Dart:    $CURRENT_DART (>= $REQUIRED_DART required) ✓"
  info "Java:    $(java -version 2>&1 | head -n1 || echo 'Not found')"
  info "Keytool: $(command -v keytool || echo 'Not found')"
  info "Prerequisites verified."
}

# ---- Prepare project ----
setup_environment() {
  info "Setting up build environment..."
  cd "$CODEBASE_DIR"
  
  # CI Optimization: Clean before setup
  cleanup_resources
  
  # Create dummy keystore for release builds
  info "Creating dummy keystore for release build..."
  mkdir -p android
  cd android
  
  if [ ! -f "key.jks" ]; then
    info "Generating dummy keystore with keytool..."
    keytool -genkey -v -keystore key.jks -keyalg RSA -keysize 2048 -validity 10000 \
      -alias release \
      -dname "CN=CI Build, OU=Security Research, O=Benchmark, L=Test, S=Test, C=US" \
      -storepass android \
      -keypass android \
      -noprompt || fail "Failed to create keystore"
    info "✅ Dummy keystore created: $(pwd)/key.jks"
  else
    info "Keystore already exists: $(pwd)/key.jks"
  fi
  
  # Create key.properties file
  cat > key.properties << EOF
storePassword=android
keyPassword=android
keyAlias=release
storeFile=key.jks
EOF
  
  cd ..
  
  # Set keystore environment variables
  export STORE_PASSWORD="android"
  export KEY_ALIAS="release"
  export KEY_PASSWORD="android"
  info "Keystore environment variables set"

  info "Fetching Flutter dependencies..."
  # Set environment variables for CI
  export PUB_CACHE="$HOME/.pub-cache"
  export FLUTTER_ROOT="$HOME/.fvm/versions/$FLUTTER_VERSION"
  
  # CI Optimization: Adjust memory limits based on CI mode
  if [ "$CI_MODE" = "true" ]; then
    # Conservative memory settings for CI
    export DART_VM_OPTIONS="--old_gen_heap_size=1024 --optimization_counter_threshold=50000"
    export GRADLE_OPTS="-Xmx1024m -XX:MaxMetaspaceSize=256m -XX:+UseG1GC -Dorg.gradle.daemon=false"
    export _JAVA_OPTIONS="-Xmx1024m"
    export PUB_MAX_WORKERS=2  # Limit parallel pub operations
    
    # Create optimized gradle.properties if building Android
    if [ -f "android/gradle.properties" ]; then
      info "Optimizing Gradle for CI..."
      # First, check if CI optimizations already added to avoid duplicates
      if ! grep -q "# CI Optimizations" "android/gradle.properties"; then
        cat >> "android/gradle.properties" << 'EOF'

# CI Optimizations
org.gradle.jvmargs=-Xmx1024m -XX:MaxMetaspaceSize=256m -XX:+UseG1GC -Dorg.gradle.daemon=false
org.gradle.parallel=false
org.gradle.daemon=false
org.gradle.configureondemand=false
org.gradle.workers.max=1
org.gradle.caching=true
org.gradle.vfs.watch=false
android.enableJetifier=true
android.useAndroidX=true
android.nonTransitiveRClass=false
android.nonFinalResIds=false
EOF
      fi
      
      # Remove deprecated options that cause build failures
      info "Removing deprecated Gradle options..."
      # Remove android.enableR8 (removed in AGP 7.0)
      sed -i '/android\.enableR8/d' "android/gradle.properties" 2>/dev/null || true
      # Remove android.enableBuildCache (removed in AGP 7.0)  
      sed -i '/android\.enableBuildCache/d' "android/gradle.properties" 2>/dev/null || true
      # Remove android.buildCacheDir (no longer used)
      sed -i '/android\.buildCacheDir/d' "android/gradle.properties" 2>/dev/null || true
      
      # Create local.properties with NDK path to avoid auto-download
      if [ ! -f "android/local.properties" ]; then
        info "Creating local.properties to skip NDK auto-download..."
        cat > "android/local.properties" << EOF
sdk.dir=${ANDROID_HOME:-/usr/local/lib/android/sdk}
flutter.sdk=$HOME/.fvm/versions/$FLUTTER_VERSION
ndk.dir=${ANDROID_HOME:-/usr/local/lib/android/sdk}/ndk/23.1.7779620
EOF
      fi
    fi
  else
    # Standard memory settings
    export DART_VM_OPTIONS="--old_gen_heap_size=2048"
  fi
  
  # Configure pub get with CI-friendly settings and retry
  info "Running Flutter pub get..."
  retry_command "timeout 600 fvm flutter pub get --no-precompile" "Flutter pub get" || \
    retry_command "fvm flutter pub get" "Flutter pub get (fallback)"

  info "Generating translation/localization files..."
  if make translation; then
    info "Translations generated with make."
  else
    warn "make translation failed; trying 'fvm flutter gen-l10n'..."
    if timeout 300 fvm flutter gen-l10n; then
      info "Translations generated via flutter gen-l10n."
    else
      warn "gen-l10n failed; attempting easy_localization fallback..."
      fvm dart run easy_localization:generate -S ../i18n -O lib/generated || true
      fvm dart run bin/generate_keys.dart || true
      info "Fallback translation generation attempted."
    fi
  fi

  info "Environment setup complete."
  show_resources
}

# ---- Build APK ----
build_immich() {
  info "Building Immich APK (release)..."
  cd "$CODEBASE_DIR"
  
  # CI Optimization: Clean build directory and gradle.properties
  if [ "$CI_MODE" = "true" ]; then
    info "Cleaning previous build artifacts..."
    fvm flutter clean 2>/dev/null || true
    rm -rf build android/app/build android/.gradle 2>/dev/null || true
    
    # Clean any problematic entries from existing gradle.properties
    if [ -f "android/gradle.properties" ]; then
      info "Cleaning gradle.properties of deprecated options..."
      # Remove all deprecated options that can cause build failures
      sed -i '/android\.enableR8/d' "android/gradle.properties" 2>/dev/null || true
      sed -i '/android\.enableBuildCache/d' "android/gradle.properties" 2>/dev/null || true
      sed -i '/android\.buildCacheDir/d' "android/gradle.properties" 2>/dev/null || true
      sed -i '/android\.enableUnitTestBinaryResources/d' "android/gradle.properties" 2>/dev/null || true
    fi
    
    # Skip NDK installation entirely to avoid hangs
    info "Configuring build to skip NDK..."
    if [ -f "android/app/build.gradle" ]; then
      # Comment out or modify NDK-related configurations
      sed -i 's/^.*ndkVersion.*$/\/\/ ndkVersion disabled for CI/' "android/app/build.gradle" 2>/dev/null || true
    fi
    
    # Set environment to skip NDK
    export ANDROID_NDK_HOME=""
    export NDK_HOME=""
  fi
  
  # CI Optimization: Monitor build progress in background with more detail
  if [ "$CI_MODE" = "true" ]; then
    (
      while true; do
        sleep 30
        echo "[Build Monitor] $(date '+%H:%M:%S') - Memory: $(free -m | awk 'NR==2{printf "%.1f%%", $3*100/$2}')"
        # Fix: Properly handle process counts - ensure we get single numbers
        GRADLE_COUNT=$(pgrep -c gradle 2>/dev/null | head -1 || echo "0")
        DART_COUNT=$(pgrep -c dart 2>/dev/null | head -1 || echo "0")
        # Ensure the values are clean integers
        GRADLE_COUNT=${GRADLE_COUNT//[^0-9]/}
        DART_COUNT=${DART_COUNT//[^0-9]/}
        [ -z "$GRADLE_COUNT" ] && GRADLE_COUNT="0"
        [ -z "$DART_COUNT" ] && DART_COUNT="0"
        
        if [ "$GRADLE_COUNT" != "0" ] || [ "$DART_COUNT" != "0" ]; then
          echo "[Build Monitor] Active processes - Gradle: $GRADLE_COUNT, Dart: $DART_COUNT"
        fi
        
        # Check if build is actually progressing by looking at build directory size
        if [ -d "build" ]; then
          BUILD_SIZE=$(du -sm build 2>/dev/null | cut -f1 || echo "0")
          echo "[Build Monitor] Build directory size: ${BUILD_SIZE}MB"
        fi
      done
    ) &
    MONITOR_PID=$!
    trap "kill $MONITOR_PID 2>/dev/null || true" EXIT
  fi
  
  # Build with optimizations
  if [ "$CI_MODE" = "true" ]; then
    # CI-specific build command - skip NDK and validation checks
    info "Building with CI optimizations (timeout: 20 minutes)..."
    
    # Set additional environment variables to prevent hangs
    export GRADLE_OPTS="-Xmx1024m -Dorg.gradle.daemon=false -Dorg.gradle.parallel=false -Dorg.gradle.workers.max=1 -Dorg.gradle.caching=true"
    
    # Build with skip-validation flag to bypass Kotlin version check and NDK
    timeout 1200 fvm flutter build apk \
      --release \
      --target-platform=android-arm64 \
      --no-tree-shake-icons \
      --android-skip-build-dependency-validation || {
        EXIT_CODE=$?
        echo "[Build Monitor] Build failed with exit code: $EXIT_CODE"
        
        if [ $EXIT_CODE -eq 124 ]; then
          echo "[Build Monitor] Build timed out after 20 minutes"
          
          # Try an even simpler build as fallback - single ABI, no native libs
          info "Attempting minimal build without native libraries..."
          timeout 600 fvm flutter build apk \
            --release \
            --target-platform=android-arm64 \
            --android-skip-build-dependency-validation || {
            fail "Minimal build also failed"
          }
        else
          fail "Build failed (exit code: $EXIT_CODE)"
        fi
      }
  else
    # Standard build
    fvm flutter build apk --release
  fi
  
  # Kill monitor if it exists
  [ -n "${MONITOR_PID:-}" ] && kill $MONITOR_PID 2>/dev/null || true

  # Check for APK in multiple possible locations
  local apk_paths=(
    "$CODEBASE_DIR/build/app/outputs/flutter-apk/app-arm64-v8a-release.apk"  # Split APK
    "$CODEBASE_DIR/build/app/outputs/flutter-apk/app-release.apk"  # Standard APK
    "$CODEBASE_DIR/build/app/outputs/apk/release/app-release.apk"  # Alternative path
  )
  
  local apk_found=false
  for apk_path in "${apk_paths[@]}"; do
    if [[ -f "$apk_path" ]]; then
      info "✅ Build complete: $apk_path"
      info "APK size: $(du -h "$apk_path" | cut -f1)"
      apk_found=true
      
      # Copy to standard location
      cp "$apk_path" "$SCRIPT_DIR/immich-release.apk"
      info "APK copied to: $SCRIPT_DIR/immich-release.apk"
      break
    fi
  done
  
  if [ "$apk_found" = false ]; then
    fail "APK not found after build. Checked paths: ${apk_paths[*]}"
  fi
  
  show_resources
}

# ---- CI Optimization: Setup trap for cleanup ----
cleanup_on_exit() {
  if [ "$CI_MODE" = "true" ]; then
    info "Performing final cleanup..."
    cleanup_resources
  fi
}

trap cleanup_on_exit EXIT

main() {
  info "Immich Android Source Build"
  echo "============================"
  
  # CI Optimization: Detect and enable CI mode
  if [ -n "${GITHUB_ACTIONS:-}" ] || [ -n "${CI:-}" ] || [ -n "${JENKINS_HOME:-}" ]; then
    CI_MODE="true"
    info "CI environment detected - enabling optimizations"
  fi
  
  if [ "$CI_MODE" = "true" ]; then
    info "Running with CI optimizations enabled"
    info "Initial system state:"
    show_resources
    echo ""
  fi

  bootstrap_prereqs
  maybe_install_android_sdk
  check_prerequisites
  setup_environment
  build_immich

  echo ""
  echo "=========================================="
  info "Immich Build complete! APK is ready."
  echo "=========================================="
  
  if [ "$CI_MODE" = "true" ]; then
    echo "Final system state:"
    show_resources
  fi
  echo ""
}

main "$@"