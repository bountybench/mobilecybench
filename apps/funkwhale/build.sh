#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Add OkHttp/Conscrypt ProGuard rules
if ! grep -q "org.conscrypt" app/proguard-rules.pro 2>/dev/null; then
    cat >> app/proguard-rules.pro << 'EOF'

# OkHttp and Conscrypt rules to fix R8 missing classes
-dontwarn org.conscrypt.**
-dontwarn okhttp3.internal.platform.**
-keep class org.conscrypt.** { *; }
-dontwarn okhttp3.internal.platform.ConscryptPlatform
-dontwarn org.conscrypt.ConscryptHostnameVerifier
-keepnames class okhttp3.internal.publicsuffix.PublicSuffixDatabase
-dontwarn org.codehaus.mojo.animal_sniffer.*
-dontwarn okhttp3.internal.platform.AndroidPlatform
EOF
fi

# Add Gson ProGuard rules
cat >> app/proguard-rules.pro << 'EOF'

# Gson rules - preserve generic signatures for TypeToken
-keepattributes Signature
-keepattributes *Annotation*
-dontwarn sun.misc.**
-keep class com.google.gson.** { *; }
-keep class * extends com.google.gson.TypeAdapter
-keep class * implements com.google.gson.TypeAdapterFactory
-keep class * implements com.google.gson.JsonSerializer
-keep class * implements com.google.gson.JsonDeserializer
-keepclassmembers,allowobfuscation class * {
  @com.google.gson.annotations.SerializedName <fields>;
}
EOF

# Integrate SSL certificate
ssl_cert="$SCRIPT_DIR/funkwhale-server/ssl/server.crt"
if [[ -f "$ssl_cert" ]]; then
    mkdir -p app/src/main/res/raw
    cp "$ssl_cert" app/src/main/res/raw/funkwhale_cert.crt

    # Patch security.xml to trust certificate
    security_xml="app/src/main/res/xml/security.xml"
    if [[ -f "$security_xml" ]] && ! grep -q "funkwhale_cert" "$security_xml"; then
        if grep -q "<trust-anchors>" "$security_xml"; then
            sed -i.bak '/<trust-anchors>/a\
        <certificates src="@raw/funkwhale_cert" />
' "$security_xml"
            rm -f "${security_xml}.bak"
        fi
    fi
fi

./gradlew clean assembleRelease --no-daemon

APK=$(find app/build/outputs/apk -name "*release*.apk" -type f | head -1)
cp "$APK" "$SCRIPT_DIR/unsigned.apk"
