#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase/SimpleLogin"

# Use debug signing (gradle provides internally) - app hardcodes keystore path
sed -i.bak 's/signingConfig signingConfigs.release/signingConfig signingConfigs.debug/' app/build.gradle

# Allow cleartext HTTP for local dev hosts (Android 9+ blocks it by default)
mkdir -p app/src/main/res/xml
cat > app/src/main/res/xml/network_security_config.xml << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="false">10.0.2.2</domain>
        <domain includeSubdomains="false">localhost</domain>
        <domain includeSubdomains="false">127.0.0.1</domain>
    </domain-config>
</network-security-config>
EOF
if ! grep -q 'networkSecurityConfig' app/src/main/AndroidManifest.xml; then
    sed -i.bak 's|android:allowBackup="true"|android:allowBackup="true" android:networkSecurityConfig="@xml/network_security_config"|' app/src/main/AndroidManifest.xml
fi

# Point default API URL to local backend (instead of https://app.simplelogin.io)
sed -i.bak 's|https://app.simplelogin.io|http://10.0.2.2:7777|' app/src/main/java/io/simplelogin/android/utils/SLSharedPreferences.kt

./gradlew --no-daemon assembleFdroidRelease

cp app/build/outputs/apk/fdroid/release/*.apk "$SCRIPT_DIR/unsigned.apk"
