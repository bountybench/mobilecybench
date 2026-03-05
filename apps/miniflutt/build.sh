#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Setup Flutter if not available
FLUTTER_HOME="$SCRIPT_DIR/flutter"
if [[ -d "$FLUTTER_HOME/bin" ]]; then
    export PATH="$FLUTTER_HOME/bin:$PATH"
elif ! command -v flutter >/dev/null 2>&1; then
    FLUTTER_VERSION="${FLUTTER_VERSION:-3.24.3}"
    OS="$(uname -s)"
    FLUTTER_HOME="$SCRIPT_DIR/flutter"

    case "$OS" in
        Linux)  FLUTTER_ARCHIVE="flutter_linux_${FLUTTER_VERSION}-stable.tar.xz"; URL_OS="linux" ;;
        Darwin) FLUTTER_ARCHIVE="flutter_macos_${FLUTTER_VERSION}-stable.zip"; URL_OS="macos" ;;
        *)      echo "Unsupported OS"; exit 1 ;;
    esac

    TMP_DIR="$(mktemp -d)"
    curl -fL "https://storage.googleapis.com/flutter_infra_release/releases/stable/${URL_OS}/${FLUTTER_ARCHIVE}" -o "$TMP_DIR/${FLUTTER_ARCHIVE}"

    if [[ "$OS" == "Linux" ]]; then
        tar xf "$TMP_DIR/${FLUTTER_ARCHIVE}" -C "$TMP_DIR"
    else
        unzip -q "$TMP_DIR/${FLUTTER_ARCHIVE}" -d "$TMP_DIR"
    fi

    rm -rf "$FLUTTER_HOME"
    mv "$TMP_DIR/flutter" "$FLUTTER_HOME"
    rm -rf "$TMP_DIR"
    export PATH="$FLUTTER_HOME/bin:$PATH"
fi

# Patch pubspec.yaml for flutter_html compatibility
python3 - pubspec.yaml << 'PYEOF'
import sys, re, pathlib
path = pathlib.Path(sys.argv[1])
text = path.read_text()
pattern = re.compile(r'(\bflutter_html[^\s:]*:\s*)([^\n]+)')
new_text, n = pattern.subn(lambda m: m.group(1) + "3.0.0-beta.2", text)
if n > 0:
    path.write_text(new_text)
PYEOF

# Write key.properties using centralized keystore from build_apk.sh
cat > android/key.properties <<EOF
storePassword=$KEYSTORE_PASSWORD
keyPassword=$KEYSTORE_ALIAS_PASSWORD
keyAlias=$KEYSTORE_ALIAS
storeFile=$KEYSTORE_PATH
EOF

flutter pub get
flutter build apk --release

cp build/app/outputs/flutter-apk/app-release.apk "$SCRIPT_DIR/unsigned.apk"
