#!/bin/bash
set -e

# Create exploit directory structure
APPLICATION_ID="com.example.overlaygrid"
APPLICATION_PATH="com/example/overlaygrid"
EXPLOIT_DIR="overlay_grid"

rm -rf "$EXPLOIT_DIR" 2>/dev/null || true
mkdir -p "$EXPLOIT_DIR"/{app/src/main/{java/${APPLICATION_PATH},res/layout},gradle/wrapper}

cd "$EXPLOIT_DIR"

echo "Creating exploit project structure..."

# Project configuration
cat > settings.gradle << 'EOF'
include ':app'
EOF

cat > build.gradle << 'EOF'
buildscript {
    ext.kotlin_version = '1.8.22'
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        classpath "org.jetbrains.kotlin:kotlin-gradle-plugin:$kotlin_version" // ✅ Add this
        classpath 'com.android.tools.build:gradle:8.1.4'
    }
}

allprojects {
    repositories {
        google()
        mavenCentral()
    }

    configurations.all {
        resolutionStrategy {
            force 'org.jetbrains.kotlin:kotlin-stdlib:1.8.22'
            force 'org.jetbrains.kotlin:kotlin-stdlib-jdk7:1.8.22'
            force 'org.jetbrains.kotlin:kotlin-stdlib-jdk8:1.8.22'
        }
    }
}
EOF

cat > app/build.gradle << EOF
plugins {
    id 'com.android.application'
    id 'org.jetbrains.kotlin.android'  // Added Kotlin plugin
}

android {
    namespace 'com.example.overlaygrid'
    compileSdk 34

    defaultConfig {
        applicationId "com.example.overlaygrid"
        minSdk 21
        targetSdk 34
        versionCode 1
        versionName "1.0"
    }

    buildTypes {
        release {
            minifyEnabled false
        }
    }

    compileOptions {
        sourceCompatibility JavaVersion.VERSION_1_8
        targetCompatibility JavaVersion.VERSION_1_8
    }

    kotlinOptions {
        jvmTarget = "1.8"  // Kotlin JVM target aligned to Java 1.8
    }
}

dependencies {
    implementation 'androidx.appcompat:appcompat:1.7.1'
    implementation "org.jetbrains.kotlin:kotlin-stdlib:1.8.22"  // Kotlin stdlib added
}
EOF

cat > "gradle.properties" << 'EOF'
android.useAndroidX=true
android.enableJetifier=true
EOF

# Android manifest
cat > app/src/main/AndroidManifest.xml << 'EOF'
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.overlaygrid">

    <uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />


    <application
        android:allowBackup="true"
        android:label="Overlay Grid"
        android:theme="@style/Theme.AppCompat.Light.NoActionBar">
        
        <activity android:name=".MainActivity"
        android:exported="true"
        >
            <intent-filter>
                <action android:name="android.intent.action.MAIN"/>
                <category android:name="android.intent.category.LAUNCHER"/>
            </intent-filter>
        </activity>

        <service android:name=".OverlayService"
            android:exported="true" />
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
cat > app/src/main/java/${APPLICATION_PATH}/MainActivity.kt << EOF 
package com.example.overlaygrid

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {

    private val OVERLAY_PERMISSION_REQ_CODE = 1234

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
            val intent = Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName"))
            startActivityForResult(intent, OVERLAY_PERMISSION_REQ_CODE)
        } else {
            startOverlayService()
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == OVERLAY_PERMISSION_REQ_CODE) {
            if (Settings.canDrawOverlays(this)) {
                startOverlayService()
            } else {
                Toast.makeText(this, "Permission not granted", Toast.LENGTH_SHORT).show()
            }
        }
        super.onActivityResult(requestCode, resultCode, data)
    }

    private fun startOverlayService() {
        val intent = Intent(this, OverlayService::class.java)
        startService(intent)
    }
}
EOF

cat > app/src/main/java/${APPLICATION_PATH}/OverlayService.kt << EOF 
package com.example.overlaygrid

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.graphics.PixelFormat
import android.os.Build
import android.os.IBinder
import android.view.WindowManager
import androidx.core.app.NotificationCompat

class OverlayService : Service() {

    private lateinit var windowManager: WindowManager
    private lateinit var overlayView: GridOverlayView

    override fun onCreate() {
        super.onCreate()

        // Foreground service requirement (API 26+)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channelId = "overlay_grid_channel"
            val channelName = "Overlay Grid Service"

            val channel = NotificationChannel(
                channelId,
                channelName,
                NotificationManager.IMPORTANCE_DEFAULT
            )
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)

            val notification: Notification = NotificationCompat.Builder(this, channelId)
                .setContentTitle("Overlay Grid Running")
                .setSmallIcon(android.R.drawable.ic_menu_view)
                .build()

            startForeground(1, notification)
        }

        // Create overlay
        windowManager = getSystemService(WINDOW_SERVICE) as WindowManager
        overlayView = GridOverlayView(this)

        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            else
                WindowManager.LayoutParams.TYPE_PHONE,
            WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        )

        windowManager.addView(overlayView, params)
    }

    override fun onDestroy() {
        super.onDestroy()
        if (::overlayView.isInitialized) {
            windowManager.removeView(overlayView)
        }
    }

    override fun onBind(intent: Intent?): IBinder? {
        return null
    }
}

EOF

cat > app/src/main/java/${APPLICATION_PATH}/GridOverlayView.kt << 'EOF'
package com.example.overlaygrid

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.view.View

class GridOverlayView(context: Context) : View(context) {

    private val paint = Paint().apply {
        color = Color.RED
        strokeWidth = 2f
        textSize = 28f
        isAntiAlias = true
    }

    private val cellSize = 300  // pixels per grid cell

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        val w = width
        val h = height

        for (x in 0..w step cellSize) {
            canvas.drawLine(x.toFloat(), 0f, x.toFloat(), h.toFloat(), paint)
        }
        
        // Draw horizontal lines
        for (y in 0..h step cellSize) {
            canvas.drawLine(0f, y.toFloat(), w.toFloat(), y.toFloat(), paint)
        }
        
        // Draw coordinate labels at grid intersections
        for (x in 0..w step cellSize) {
            for (y in 0..h step cellSize) {
                canvas.drawText("($x,$y)", x + 5f, y + 25f, paint)
            }
        }
    }
}
EOF

echo "Building exploit APK..."

gradle wrapper
./gradlew clean
./gradlew assembleDebug
./gradlew installDebug

adb shell am start -a android.settings.action.MANAGE_OVERLAY_PERMISSION \
    -d package:com.example.overlaygrid