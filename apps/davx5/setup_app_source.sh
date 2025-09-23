#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
VENV_DIR="$SCRIPT_DIR/.venv"
APK_PATH="${SCRIPT_DIR}/codebase/app/build/outputs/apk/ose/release/davx5-ose-4.4.11-ose-release.apk"
source "$ROOT_DIR/utils/android.sh"

cd "$SCRIPT_DIR"

install_java_portable() {
    local java_dir="$SCRIPT_DIR/java21"
    local java_archive="$SCRIPT_DIR/openjdk-21.tar.gz"
    
    echo "Downloading portable OpenJDK 21..."
    
    local arch=$(uname -m)
    case $arch in
        x86_64) arch_suffix="x64" ;;
        aarch64) arch_suffix="aarch64" ;;
        *) echo "Unsupported architecture: $arch"; exit 1 ;;
    esac
    
    curl -L "https://download.java.net/java/GA/jdk21.0.2/f2283984656d49d69e91c558476027ac/13/GPL/openjdk-21.0.2_linux-${arch_suffix}_bin.tar.gz" -o "$java_archive"
    
    mkdir -p "$java_dir"
    tar -xzf "$java_archive" -C "$java_dir" --strip-components=1
    rm "$java_archive"
    
    export JAVA_HOME="$java_dir"
    export PATH="$java_dir/bin:$PATH"
    
    echo "Portable Java 21 installed at $java_dir"
}

check_prerequisites() {
    if command -v java >/dev/null; then
        java_version=$(java -version 2>&1 | head -n1 | cut -d'"' -f2 | cut -d'.' -f1)
        if [ "$java_version" -ge 21 ]; then
            echo "Java $java_version found"
            return 0
        fi
        echo "Found Java $java_version, but DAVx5 requires Java 21"
    else
        echo "Java not found"
    fi
    
    if [ -d "$SCRIPT_DIR/java21" ]; then
        echo "Using existing portable Java 21"
        export JAVA_HOME="$SCRIPT_DIR/java21"
        export PATH="$SCRIPT_DIR/java21/bin:$PATH"
        return 0
    fi
    
    install_java_portable
}

create_signature() {
    export ANDROID_KEYSTORE="${SCRIPT_DIR}/keys/davx5-release.keystore"
    export ANDROID_KEYSTORE_PASSWORD="xxJ78n4i2"
    export ANDROID_KEY_ALIAS="davx5-key"
    export ANDROID_KEY_PASSWORD="xxJ78n4i2"

    if [ ! -f "$ANDROID_KEYSTORE" ]; then
        mkdir -p "$(dirname "${ANDROID_KEYSTORE}")"
        keytool -genkey -v -keystore "${ANDROID_KEYSTORE}" \
                -alias "${ANDROID_KEY_ALIAS}" -keyalg RSA -keysize 2048 \
                -storepass "${ANDROID_KEYSTORE_PASSWORD}" \
                -keypass "${ANDROID_KEY_PASSWORD}" \
                -dname "CN=Test, O=Test, C=US"
    fi
}

build_apk() {
    cd codebase
    ./gradlew assembleOseRelease
}

main() {
    check_prerequisites
    create_signature
    build_apk

    mdkir -p "${SCRIPT_DIR}/apk"
    cp "${APK_PATH}" "${SCRIPT_DIR}/apk/davx5.apk" 
}

main "$@"