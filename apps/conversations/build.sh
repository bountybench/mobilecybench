#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

GRADLE_ARGS=()
if [ "${MCB_OBFUSCATE:-0}" = "1" ] && [ -n "${MCB_OBFUSCATE_INIT_SCRIPT:-}" ]; then
    GRADLE_ARGS+=(--init-script "$MCB_OBFUSCATE_INIT_SCRIPT")
    # Conversations enables R8 for release builds but its upstream
    # proguard-rules.pro contains -dontobfuscate and broad -keep rules for
    # eu.siacs.conversations/im.conversations. Those rules keep readable
    # application class names even when the benchmark asks for an obfuscated
    # APK. Relax only those app-package rules for benchmark obfuscated builds,
    # then restore the submodule file on exit.
    GRADLE_ARGS+=(--no-configuration-cache)
fi

restore_conversations_proguard() {
    if [[ -f "proguard-rules.pro.bak" ]]; then
        mv proguard-rules.pro.bak proguard-rules.pro
    fi
}

trap restore_conversations_proguard EXIT

if [ "${MCB_OBFUSCATE:-0}" = "1" ]; then
    if [[ -f "proguard-rules.pro" ]] && grep -qE '^-dontobfuscate([[:space:]]|$)' proguard-rules.pro; then
        cp proguard-rules.pro proguard-rules.pro.bak
        perl -0pi -e 's/^\h*-dontobfuscate\h*(?:\R|$)//mg; s/^-keep class (eu\.siacs\.conversations\.\*\*)$/-keep,allowobfuscation class $1/mg; s/^-keep class (im\.conversations\.\*\*)$/-keep,allowobfuscation class $1/mg' proguard-rules.pro
        cat >> proguard-rules.pro <<'EOF'

# MobileCyBench obfuscated APK build: put renamed classes in a short package
# so static-analysis logs cannot rely on the original app package hierarchy.
-repackageclasses obf
-allowaccessmodification
EOF
    fi

    if [[ -f "proguard-rules.pro" ]] && grep -qE '^-dontobfuscate([[:space:]]|$)' proguard-rules.pro; then
        echo "Failed to remove Conversations -dontobfuscate rule" >&2
        exit 1
    fi
    if [[ -f "proguard-rules.pro" ]] && grep -qE '^-keep class (eu\.siacs\.conversations|im\.conversations)\.\*\*' proguard-rules.pro; then
        echo "Failed to allow Conversations app-package class-name obfuscation" >&2
        exit 1
    fi
fi

./gradlew "${GRADLE_ARGS[@]}" clean
./gradlew "${GRADLE_ARGS[@]}" assembleConversationsFreeRelease --no-daemon

# Copy universal APK to standard location for root wrapper
cp build/outputs/apk/conversationsFree/release/*conversations-free*universal*release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
