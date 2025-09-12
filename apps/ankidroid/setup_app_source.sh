#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/codebase"

# ---- Resolve a usable JDK 17 (macOS + Linux) ----
resolve_java17() {
  # 1) If JAVA_HOME is already 17, keep it
  if [[ -n "${JAVA_HOME:-}" ]] && "$JAVA_HOME/bin/java" -version 2>&1 | grep -q 'version "17'; then
    echo "$JAVA_HOME"; return
  fi
  # 2) macOS helper
  if command -v /usr/libexec/java_home >/dev/null 2>&1; then
    jh="$(/usr/libexec/java_home -v 17 2>/dev/null || true)"
    [[ -n "$jh" ]] && echo "$jh" && return
  fi
  # 3) Homebrew (Apple Silicon / Intel)
  for p in \
    /opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home \
    /usr/local/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
  do [[ -x "$p/bin/java" ]] && echo "$p" && return; done
  # 4) Common Linux locations
  for p in \
    /usr/lib/jvm/java-17-openjdk-amd64 \
    /usr/lib/jvm/java-17-openjdk \
    /usr/lib/jvm/java-17-openjdk-arm64
  do [[ -x "$p/bin/java" ]] && echo "$p" && return; done

  echo "ERROR: JDK 17 not found. Please install it (e.g., 'brew install openjdk@17' on macOS)." >&2
  exit 1
}

export JAVA_HOME="$(resolve_java17)"
export PATH="$JAVA_HOME/bin:$PATH"
echo "Using JAVA_HOME=$JAVA_HOME"
java -version

# Optional: wire Android SDK if present
[[ -n "${ANDROID_HOME:-}" && -d "$ANDROID_HOME" ]] && echo "sdk.dir=$ANDROID_HOME" > local.properties

# ---- Build AnkiDroid debug APK ----
./gradlew \
  --no-daemon \
  -Dorg.gradle.java.home="$JAVA_HOME" \
  :AnkiDroid:assembleFullDebug \
  -x lint \
  -x :AnkiDroid:installGitHook \
  -x :AnkiDroid:stripFullDebugDebugSymbols \
  -x :AnkiDroid:stripPlayDebugDebugSymbols \
  -x :AnkiDroid:stripAmazonDebugDebugSymbols

# ---- Copy first debug APK to apps/ankidroid/app.apk ----
APK_PATH="$(find . -type f -name '*full*debug*.apk' | head -n 1)"
[[ -n "${APK_PATH:-}" ]] || { echo "No debug APK found"; exit 1; }
cp -f "$APK_PATH" ../app.apk
echo "Built APK at apps/ankidroid/app.apk"