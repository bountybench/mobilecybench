#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

# Cross-platform sed
sed_inplace() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "$@"
    else
        sed -i "$@"
    fi
}

GRADLE_ARGS=()
if [[ "${MCB_OBFUSCATE:-0}" = "1" && -n "${MCB_OBFUSCATE_INIT_SCRIPT:-}" ]]; then
    GRADLE_ARGS+=(--init-script "$MCB_OBFUSCATE_INIT_SCRIPT")
fi

configure_obfuscation() {
    [[ "${MCB_OBFUSCATE:-0}" = "1" ]] || return 0

    for rules_file in app/proguard-rules.pro termux-shared/proguard-rules.pro; do
        [[ -f "$rules_file" ]] && sed_inplace '/^-dontobfuscate$/d' "$rules_file"
    done

    grep -q "MobileCyBench Termux obfuscation keeps" app/proguard-rules.pro && return 0
    cat >> app/proguard-rules.pro <<'EOF'

# MobileCyBench Termux obfuscation keeps: preserve Android/plugin/JNI entry
# points while allowing internal implementation classes to be renamed by R8.
-keepattributes *Annotation*,Signature,InnerClasses,EnclosingMethod

-keep class com.termux.app.TermuxApplication { *; }
-keep class com.termux.app.TermuxActivity { *; }
-keep class com.termux.app.activities.HelpActivity { *; }
-keep class com.termux.app.activities.SettingsActivity { *; }
-keep class com.termux.shared.activities.ReportActivity { *; }
-keep class com.termux.shared.activities.ReportActivity$ReportActivityBroadcastReceiver { *; }
-keep class com.termux.filepicker.TermuxFileReceiverActivity { *; }
-keep class com.termux.filepicker.TermuxDocumentsProvider { *; }
-keep class com.termux.app.TermuxOpenReceiver { *; }
-keep class com.termux.app.TermuxOpenReceiver$ContentProvider { *; }
-keep class com.termux.app.TermuxService { *; }
-keep class com.termux.app.RunCommandService { *; }

-keep class com.termux.shared.termux.TermuxConstants { *; }
-keep class com.termux.shared.termux.TermuxConstants$* { *; }
-keep class com.termux.shared.models.ExecutionCommand { *; }
-keep class com.termux.shared.models.ExecutionCommand$* { *; }
-keep class com.termux.shared.models.ResultConfig { *; }
-keep class com.termux.shared.models.ResultData { *; }
-keep class com.termux.shared.models.ReportInfo { *; }
-keep class com.termux.shared.models.TextIOInfo { *; }
-keep class com.termux.shared.models.errors.** { *; }
-keep class com.termux.shared.shell.ResultSender { *; }

-keep class com.termux.terminal.JNI { *; }
-keep class com.termux.app.TermuxInstaller {
    public static native byte[] getZip();
}
-keepclasseswithmembernames class * {
    native <methods>;
}
EOF
}

# Install NDK if available
if command -v sdkmanager >/dev/null 2>&1; then
    sdkmanager "ndk;24.0.8215888" --no_https 2>/dev/null || true
fi
unset ANDROID_NDK_HOME ANDROID_NDK NDK_HOME

# Update Gradle and AGP versions
sed_inplace 's|distributionUrl=.*|distributionUrl=https\\://services.gradle.org/distributions/gradle-8.13-bin.zip|' gradle/wrapper/gradle-wrapper.properties
sed_inplace 's|classpath.*gradle:.*|classpath '\''com.android.tools.build:gradle:8.9.3'\''|' build.gradle

# Patch gradle.properties - update SDK to 34 and JVM args
# v0.118+ uses multi-line jvmargs with backslash continuations; collapse to one line first
sed_inplace -e '/^org\.gradle\.jvmargs=/,/[^\\]$/{/^org\.gradle\.jvmargs=/!d;}' gradle.properties
sed_inplace \
    -e 's|^org.gradle.jvmargs=.*|org.gradle.jvmargs=-Xmx2048M --add-opens=java.base/java.io=ALL-UNNAMED --add-opens=java.base/java.lang=ALL-UNNAMED --add-opens=java.base/java.util=ALL-UNNAMED|' \
    -e 's|^ndkVersion=.*|ndkVersion=24.0.8215888|' \
    -e 's|^targetSdkVersion=.*|targetSdkVersion=34|' \
    -e 's|^compileSdkVersion=.*|compileSdkVersion=34|' \
    gradle.properties

# Patch app/build.gradle - NDK version and namespace
sed_inplace 's|ndkVersion = System.getenv("JITPACK_NDK_VERSION") ?: project.properties.ndkVersion|ndkVersion = "24.0.8215888"|' app/build.gradle
if ! grep -q "namespace" app/build.gradle; then
    sed_inplace "/^android {/a\\
    namespace 'com.termux'
" app/build.gradle
fi

# Add packagingOptions for native libraries
if ! grep -q "packagingOptions" app/build.gradle; then
    sed_inplace "/^android {/a\\
    packagingOptions {\\
        jniLibs {\\
            useLegacyPackaging = true\\
        }\\
    }\\
" app/build.gradle
fi

# Patch AndroidManifest.xml (idempotent — safe to run multiple times)
# Add android:exported="true" only if not already present on each component
grep -A1 'android:name="\.app\.TermuxActivity"' app/src/main/AndroidManifest.xml | grep -q 'exported' || \
    sed_inplace '/android:name="\.app\.TermuxActivity"/a\
            android:exported="true"' app/src/main/AndroidManifest.xml
grep -A1 'android:name="\.filepicker\.TermuxFileReceiverActivity"' app/src/main/AndroidManifest.xml | grep -q 'exported' || \
    sed_inplace '/android:name="\.filepicker\.TermuxFileReceiverActivity"/a\
            android:exported="true"' app/src/main/AndroidManifest.xml
grep -A1 'android:name="\.HomeActivity"' app/src/main/AndroidManifest.xml | grep -q 'exported' || \
    sed_inplace '/android:name="\.HomeActivity"/a\
            android:exported="true"' app/src/main/AndroidManifest.xml
# Add foregroundServiceType only if not already present on each service
grep -A1 'android:name="\.app\.TermuxService"' app/src/main/AndroidManifest.xml | grep -q 'foregroundServiceType' || \
    sed_inplace '/android:name="\.app\.TermuxService"/a\
            android:foregroundServiceType="dataSync"' app/src/main/AndroidManifest.xml
grep -A1 'android:name="\.app\.RunCommandService"' app/src/main/AndroidManifest.xml | grep -q 'foregroundServiceType' || \
    sed_inplace '/android:name="\.app\.RunCommandService"/a\
            android:foregroundServiceType="dataSync"' app/src/main/AndroidManifest.xml
if ! grep -q 'FOREGROUND_SERVICE_DATA_SYNC' app/src/main/AndroidManifest.xml; then
    sed_inplace '/<uses-permission android:name="android.permission.FOREGROUND_SERVICE" \/>/a\
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_DATA_SYNC" \/>' app/src/main/AndroidManifest.xml
fi

# Patch Java files for deprecated APIs
sed_inplace '/settings\.setAppCacheEnabled(false);/d' app/src/main/java/com/termux/app/activities/HelpActivity.java

git checkout HEAD -- termux-shared/src/main/java/com/termux/shared/interact/MessageDialogUtils.java
sed_inplace 's/R\.style\.Theme_AppCompat_Light_Dialog/0/' termux-shared/src/main/java/com/termux/shared/interact/MessageDialogUtils.java

# PendingIntent flags for Android 12+. These are general targetSdkVersion=34
# compatibility patches, not obfuscation-specific changes.
sed_inplace 's/PendingIntent\.getActivity(this, 0, notificationIntent, 0)/PendingIntent.getActivity(this, 0, notificationIntent, PendingIntent.FLAG_IMMUTABLE)/' app/src/main/java/com/termux/app/TermuxService.java
sed_inplace 's/PendingIntent\.getService(this, 0, exitIntent, 0)/PendingIntent.getService(this, 0, exitIntent, PendingIntent.FLAG_IMMUTABLE)/' app/src/main/java/com/termux/app/TermuxService.java
sed_inplace 's/PendingIntent\.getService(this, 0, toggleWakeLockIntent, 0)/PendingIntent.getService(this, 0, toggleWakeLockIntent, PendingIntent.FLAG_IMMUTABLE)/' app/src/main/java/com/termux/app/TermuxService.java

git checkout HEAD -- app/src/main/java/com/termux/app/utils/CrashUtils.java
sed_inplace 's/PendingIntent\.FLAG_UPDATE_CURRENT)/PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE)/g' app/src/main/java/com/termux/app/utils/CrashUtils.java
sed_inplace 's/R\.drawable\.ic_error_notification/com.termux.shared.R.drawable.ic_error_notification/' app/src/main/java/com/termux/app/utils/CrashUtils.java

git checkout HEAD -- app/src/main/java/com/termux/app/utils/PluginUtils.java
sed_inplace 's/PendingIntent\.FLAG_UPDATE_CURRENT)/PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE)/g' app/src/main/java/com/termux/app/utils/PluginUtils.java
sed_inplace 's/R\.drawable\.ic_error_notification/com.termux.shared.R.drawable.ic_error_notification/' app/src/main/java/com/termux/app/utils/PluginUtils.java

sed_inplace 's/registerReceiver(mTermuxActivityBroadcastReceiver, intentFilter)/registerReceiver(mTermuxActivityBroadcastReceiver, intentFilter, Context.RECEIVER_NOT_EXPORTED)/' app/src/main/java/com/termux/app/TermuxActivity.java

# Fix references to termux-shared resources (AGP 8.0+ with namespaces requires qualified R)
sed_inplace 's/R\.raw\.bell/com.termux.shared.R.raw.bell/' app/src/main/java/com/termux/app/terminal/TermuxTerminalSessionClient.java
sed_inplace 's/R\.string\.action_yes/com.termux.shared.R.string.action_yes/' app/src/main/java/com/termux/app/terminal/TermuxTerminalViewClient.java
sed_inplace 's/R\.string\.action_no/com.termux.shared.R.string.action_no/' app/src/main/java/com/termux/app/terminal/TermuxTerminalViewClient.java

# Add namespaces to library modules
for module_ns in "terminal-emulator:com.termux.terminal" "termux-shared:com.termux.shared" "terminal-view:com.termux.view"; do
    module="${module_ns%%:*}"
    ns="${module_ns##*:}"
    if [[ -f "$module/build.gradle" ]] && ! grep -q "namespace" "$module/build.gradle"; then
        sed_inplace "/^android {/a\\
    namespace '$ns'
" "$module/build.gradle"
    fi
done

# Fix deprecated classifier() and remove publishing blocks
for build_file in terminal-emulator/build.gradle termux-shared/build.gradle terminal-view/build.gradle; do
    if [[ -f "$build_file" ]]; then
        sed_inplace 's|classifier "sources"|archiveClassifier.set("sources")|' "$build_file"
        sed_inplace '/^afterEvaluate {/,/^}$/d' "$build_file"
    fi
done

# Remove package attributes from library manifests
for manifest in terminal-emulator/src/main/AndroidManifest.xml termux-shared/src/main/AndroidManifest.xml terminal-view/src/main/AndroidManifest.xml; do
    [[ -f "$manifest" ]] && sed_inplace 's/ package="[^"]*"//' "$manifest"
done

# Remove ndk.dir from local.properties
[[ -f "local.properties" ]] && sed_inplace '/^ndk\.dir=/d' local.properties

configure_obfuscation

# Build
./gradlew --stop
./gradlew "${GRADLE_ARGS[@]}" clean
./gradlew "${GRADLE_ARGS[@]}" downloadBootstraps --no-daemon
./gradlew "${GRADLE_ARGS[@]}" assembleRelease --no-daemon

# Find and copy APK
APK=$(find . -path "*/build/outputs/apk/release/*universal*release*.apk" -type f | head -1)
[[ -z "$APK" ]] && APK=$(find . -path "*/build/outputs/apk/release/*.apk" -type f | head -1)
cp "$APK" "$SCRIPT_DIR/unsigned.apk"
