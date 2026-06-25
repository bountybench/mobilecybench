#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${SCRIPT_DIR}"
APK_OUT_DIR="${ROOT_DIR}/apk"
LOG_PREFIX="[setup_app_source]"
LOG_FILE="${SCRIPT_DIR}/setup_app_source.log"
CODEBASE_DIR="${SCRIPT_DIR}/codebase"

mkdir -p "${APK_OUT_DIR}"

# ensure correct java
if command -v /usr/libexec/java_home >/dev/null 2>&1; then
  JAVA17=$(/usr/libexec/java_home -v 17 2>/dev/null || true)
  if [[ -n "$JAVA17" ]]; then
    export JAVA_HOME="$JAVA17"
  fi
fi


exec > >(tee -a "$LOG_FILE") 2>&1
info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*"; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*"; exit 1; }

check_prerequisites() {
    info "Checking prerequisites (Java)..."

    if ! command -v java >/dev/null 2>&1; then
        error "Java not found. Please install Java 17."
    fi

    info "Prerequisites verified."
}

setup_flutter() {
    # If flutter already exists in PATH, just use it and return
    if command -v flutter >/dev/null 2>&1; then
        info "Flutter already installed: $(command -v flutter)"
        return 0
    fi

    info "Flutter not found. Installing local Flutter SDK..."

    FLUTTER_VERSION="${FLUTTER_VERSION:-3.24.3}"
    OS="$(uname -s)"

    case "${OS}" in
      Linux)
        FLUTTER_ARCHIVE="flutter_linux_${FLUTTER_VERSION}-stable.tar.xz"
        FLUTTER_URL="https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/${FLUTTER_ARCHIVE}"
        ;;
      Darwin)
        FLUTTER_ARCHIVE="flutter_macos_${FLUTTER_VERSION}-stable.zip"
        FLUTTER_URL="https://storage.googleapis.com/flutter_infra_release/releases/stable/macos/${FLUTTER_ARCHIVE}"
        ;;
      *)
        error "Unsupported OS '${OS}'. Only Linux and macOS are supported."
        ;;
    esac

    FLUTTER_HOME="${SCRIPT_DIR}/flutter"
    info "Will install Flutter ${FLUTTER_VERSION} to ${FLUTTER_HOME}"

    TMP_DIR="$(mktemp -d)"
    trap 'rm -rf "${TMP_DIR}"' EXIT

    # Save current dir so we can restore it later
    PREV_DIR="$(pwd)"

    cd "${TMP_DIR}"
    info "Downloading Flutter from ${FLUTTER_URL}..."
    curl -fL "${FLUTTER_URL}" -o "${FLUTTER_ARCHIVE}"

    info "Extracting Flutter..."
    if [ "${OS}" = "Linux" ]; then
        tar xf "${FLUTTER_ARCHIVE}"
    else
        unzip -q "${FLUTTER_ARCHIVE}"
    fi

    if [ ! -d flutter ]; then
        error "Flutter archive did not contain expected 'flutter/' directory"
    fi

    rm -rf "${FLUTTER_HOME}"
    mv flutter "${FLUTTER_HOME}"

    # Restore original directory
    cd "${PREV_DIR}"

    export PATH="${FLUTTER_HOME}/bin:${PATH}"

    info "Flutter installed successfully"
    info "Flutter version: $(flutter --version)"
}


patch_pubspec_for_ci() {
    local PUBSPEC="${CODEBASE_DIR}/pubspec.yaml"

    if [[ ! -f "${PUBSPEC}" ]]; then
        error "pubspec.yaml not found at ${PUBSPEC}"
    fi

    info "Patching pubspec.yaml for CI compatibility (flutter_html ecosystem)..."

    python3 - "$PUBSPEC" << 'PYEOF'
import sys, re, pathlib

path = pathlib.Path(sys.argv[1])
text = path.read_text()

# Matches ANY dependency that begins with "flutter_html"
# Example: flutter_html_video:, flutter_html_audio:, flutter_html_table:
pattern = re.compile(r'(\bflutter_html[^\s:]*:\s*)([^\n]+)')

def repl(match):
    return match.group(1) + "3.0.0-beta.2"

new_text, n = pattern.subn(repl, text)

if n > 0:
    path.write_text(new_text)
PYEOF

    info "pubspec.yaml patched (all flutter_html* → 3.0.0-beta.2)."
}


ensure_gradle_release_keystore() {
    info "Ensuring Gradle release keystore + key.properties exist..."

    # Where we'll keep our CI keystore
    local KEYS_DIR="${ROOT_DIR}/various"
    local KEYSTORE_PATH="${KEYS_DIR}/miniflutt-release.jks"
    local KEY_ALIAS="miniflutt"
    local KEYSTORE_PASS="android"
    local KEY_PASS="android"

    mkdir -p "${KEYS_DIR}"

    # Create keystore if missing
    if [[ ! -f "${KEYSTORE_PATH}" ]]; then
        info "Generating release keystore at ${KEYSTORE_PATH}..."
        keytool -genkeypair \
            -keystore "${KEYSTORE_PATH}" \
            -storepass "${KEYSTORE_PASS}" \
            -keypass "${KEY_PASS}" \
            -alias "${KEY_ALIAS}" \
            -keyalg RSA \
            -keysize 2048 \
            -validity 10000 \
            -dname "CN=Miniflutt,O=CySuite,C=US"
    fi

    # Write android/key.properties so build.gradle can pick it up
    local KEYP_FILE="${CODEBASE_DIR}/android/key.properties"
    info "Writing ${KEYP_FILE} for Gradle signing config..."

    cat > "${KEYP_FILE}" <<EOF
        storePassword=${KEYSTORE_PASS}
        keyPassword=${KEY_PASS}
        keyAlias=${KEY_ALIAS}
        storeFile=${KEYSTORE_PATH}
EOF
}

ensure_android_build_tools() {
    info "Ensuring legacy Android build tools for miniflutt..."

    local SDKMANAGER="${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager"

    if [[ ! -x "$SDKMANAGER" ]]; then
        error "sdkmanager not found at $SDKMANAGER; is the Android SDK installed?"
    fi

    # Install the build-tools/platform that miniflutt's Gradle file wants
    "$SDKMANAGER" "build-tools;25.0.1" "platforms;android-25" >/dev/null

    info "Legacy build-tools 25.0.1 and platform android-25 installed."
}




build_apk() {
    info "Preparing Gradle release signing config..."
    ensure_gradle_release_keystore

    info "Running flutter pub get..."
    flutter pub get

    info "Building release APK..."
    echo "[setup] Patching Gradle + AGP for compatibility"

    flutter build apk --release

    local BUILT_APK="build/app/outputs/flutter-apk/app-release.apk"

    if [[ ! -f "${BUILT_APK}" ]]; then
        error "Expected APK not found at ${BUILT_APK}"
    fi

    # Just copy the signed release APK into our final location.
    # Gradle has already zipaligned + signed it using the keystore above.
    local FINAL_APK="${APK_OUT_DIR}/miniflutt.apk"
    mkdir -p "${APK_OUT_DIR}"
    cp "${BUILT_APK}" "${FINAL_APK}"

    info "Copied signed release APK to ${FINAL_APK}"
}


main() {
    info "miniflutt Android Setup"
    echo "====================="

    CODEBASE_DIR="${SCRIPT_DIR}/codebase"
    if [[ ! -d "$CODEBASE_DIR" ]]; then
        error "miniflutt codebase directory not found at $CODEBASE_DIR"
    fi

    cd "$CODEBASE_DIR"

    check_prerequisites
    setup_flutter
    ensure_android_build_tools
    patch_pubspec_for_ci
    build_apk

    echo ""
    echo "=========================================="
    info "miniflutt Build complete! miniflutt is ready to be installed"
    echo "=========================================="
    echo ""
}

main "$@"
