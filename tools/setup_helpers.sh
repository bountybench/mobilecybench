#!/usr/bin/env bash
# Shared helpers for app source builds.
# Source this file from app-specific setup_app_source.sh scripts.
set -euo pipefail

LOG_PREFIX="[setup_helper]"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
error(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

require_cmd(){ command -v "$1" >/dev/null 2>&1 || error "Missing command: $1"; }

# Resolve and export a usable JDK. Default is 17. Pass desired version as first arg.
resolve_java(){
  local target="${1:-17}"

  # If JAVA_HOME already matches, keep it.
  if [[ -n "${JAVA_HOME:-}" ]] && "$JAVA_HOME/bin/java" -version 2>&1 | grep -q "version \"$target"; then
    info "Using existing JAVA_HOME=$JAVA_HOME"
    export PATH="$JAVA_HOME/bin:$PATH"
    return 0
  fi

  # macOS java_home helper
  if command -v /usr/libexec/java_home >/dev/null 2>&1; then
    local jh
    jh="$(/usr/libexec/java_home -v "$target" 2>/dev/null || true)"
    if [[ -n "$jh" ]]; then
      export JAVA_HOME="$jh"
      export PATH="$JAVA_HOME/bin:$PATH"
      info "Resolved JAVA_HOME via java_home: $JAVA_HOME"
      return 0
    fi
  fi

  # Homebrew locations (Apple/Intel)
  local brew_candidates=(
    "/opt/homebrew/opt/openjdk@${target}/libexec/openjdk.jdk/Contents/Home"
    "/usr/local/opt/openjdk@${target}/libexec/openjdk.jdk/Contents/Home"
  )
  for p in "${brew_candidates[@]}"; do
    if [[ -x "$p/bin/java" ]]; then
      export JAVA_HOME="$p"
      export PATH="$JAVA_HOME/bin:$PATH"
      info "Resolved JAVA_HOME via Homebrew: $JAVA_HOME"
      return 0
    fi
  done

  # Common Linux locations
  local linux_candidates=(
    "/usr/lib/jvm/java-${target}-openjdk-amd64"
    "/usr/lib/jvm/java-${target}-openjdk-arm64"
    "/usr/lib/jvm/java-${target}-openjdk"
    "/usr/lib/jvm/java-${target}"
  )
  for p in "${linux_candidates[@]}"; do
    if [[ -x "$p/bin/java" ]]; then
      export JAVA_HOME="$p"
      export PATH="$JAVA_HOME/bin:$PATH"
      info "Resolved JAVA_HOME via Linux path: $JAVA_HOME"
      return 0
    fi
  done

  error "JDK $target not found. Install it or set JAVA_HOME."
}

# Resolve Android SDK root and export ANDROID_HOME + ANDROID_SDK_ROOT.
resolve_android_sdk(){
  local candidates=(
    "${ANDROID_HOME:-}"
    "${ANDROID_SDK_ROOT:-}"
    "$HOME/Library/Android/sdk"
    "$HOME/.android-sdk"
    "$HOME/Android/Sdk"
    "/usr/local/share/android-sdk"
    "/usr/local/lib/android/sdk"
  )

  for d in "${candidates[@]}"; do
    if [[ -n "$d" && -d "$d" ]]; then
      export ANDROID_HOME="$d"
      export ANDROID_SDK_ROOT="$d"
      info "Using Android SDK at $d"
      return 0
    fi
  done

  warn "Android SDK not found. Set ANDROID_HOME/ANDROID_SDK_ROOT."
  return 1
}

# Write local.properties sdk.dir for a Gradle project.
write_local_properties(){
  local project_dir="$1"
  [[ -d "$project_dir" ]] || error "Project dir missing: $project_dir"

  if [[ -z "${ANDROID_SDK_ROOT:-}" ]]; then
    warn "ANDROID_SDK_ROOT not set; skipping local.properties."
    return 0
  fi

  printf 'sdk.dir=%s\n' "$ANDROID_SDK_ROOT" > "$project_dir/local.properties"
  info "Wrote $project_dir/local.properties"
}

# Ensure gradlew exists and is executable.
ensure_gradlew(){
  local project_dir="$1"
  [[ -f "$project_dir/gradlew" ]] || error "gradlew missing in $project_dir"
  chmod +x "$project_dir/gradlew" 2>/dev/null || true
}

# Ensure a debug keystore exists; exports KEYSTORE_PATH for convenience.
ensure_debug_keystore(){
  local keystore="${1:-$HOME/.android/debug.keystore}"
  if [[ ! -f "$keystore" ]]; then
    mkdir -p "$(dirname "$keystore")"
    keytool -genkey -v -keystore "$keystore" \
      -alias androiddebugkey -keyalg RSA -keysize 2048 \
      -validity 10000 -storepass android -keypass android \
      -dname "CN=Android Debug, O=Android, C=US"
    info "Generated debug keystore at $keystore"
  fi
  export KEYSTORE_PATH="$keystore"
}

# Sign an unsigned APK with the debug keystore. First arg: unsigned apk path.
sign_apk_debug(){
  local apk_unsigned="$1"
  [[ -f "$apk_unsigned" ]] || error "Unsigned APK not found: $apk_unsigned"
  ensure_debug_keystore

  [[ -n "${ANDROID_HOME:-}" ]] || error "ANDROID_HOME not set; apksigner unavailable"
  local apksigner
  apksigner="$(find "$ANDROID_HOME/build-tools" -name apksigner -type f 2>/dev/null | sort | tail -1)"

  local apk_signed="${apk_unsigned/-unsigned.apk/.apk}"

  if [[ -n "$apksigner" && -x "$apksigner" ]]; then
    "$apksigner" sign \
      --ks "$KEYSTORE_PATH" \
      --ks-key-alias androiddebugkey \
      --ks-pass pass:android \
      --key-pass pass:android \
      --v2-signing-enabled true \
      "$apk_unsigned"
  else
    warn "apksigner not found; falling back to jarsigner"
    jarsigner -verbose -sigalg SHA256withRSA -digestalg SHA256 \
      -keystore "$KEYSTORE_PATH" -storepass android -keypass android \
      "$apk_unsigned" androiddebugkey
  fi

  mv "$apk_unsigned" "$apk_signed"
  info "Signed APK: $apk_signed"
  printf '%s\n' "$apk_signed"
}

# Pick the first matching APK given a list of glob patterns (in order).
# Usage: pick_apk <base_dir> "glob1" "glob2" ...
pick_apk(){
  local base="$1"; shift || true
  local pattern apk
  for pattern in "$@"; do
    apk="$(find "$base" -type f -path "$pattern" -print 2>/dev/null | head -n 1 || true)"
    if [[ -n "$apk" ]]; then
      printf '%s\n' "$apk"
      return 0
    fi
  done
  return 1
}

copy_apk(){
  local src="$1" dest="$2"
  [[ -f "$src" ]] || error "APK to copy not found: $src"
  mkdir -p "$(dirname "$dest")"
  cp -f "$src" "$dest"
  info "Copied APK to $dest"
}

# Guard: if executed directly, print usage and exit.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "This file is intended to be sourced from setup_app_source.sh scripts." >&2
  exit 1
fi
