#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

GRADLE_ARGS=()
if [ "${MCB_OBFUSCATE:-0}" = "1" ] && [ -n "${MCB_OBFUSCATE_INIT_SCRIPT:-}" ]; then
    GRADLE_ARGS+=(--init-script "$MCB_OBFUSCATE_INIT_SCRIPT")
    # Jerboa's release build already runs R8, but recent upstream commits set
    # postprocessing.isObfuscate=false to keep readable stack traces. The
    # generic init script can turn R8 on, but it cannot override this
    # app-specific "do not rename classes" switch. Flip it only for benchmark
    # obfuscated APK builds, then restore the submodule file on exit.
    GRADLE_ARGS+=(--no-configuration-cache)
fi

restore_jerboa_build_files() {
    if [[ -f "app/build.gradle.kts.bak" ]]; then
        mv app/build.gradle.kts.bak app/build.gradle.kts
    fi
    if [[ -f "app/build.gradle.bak" ]]; then
        mv app/build.gradle.bak app/build.gradle
    fi
}

trap restore_jerboa_build_files EXIT

if [ "${MCB_OBFUSCATE:-0}" = "1" ]; then
    if [[ -f "app/build.gradle.kts" ]] && grep -qE 'isObfuscate[[:space:]]*=[[:space:]]*false' app/build.gradle.kts; then
        cp app/build.gradle.kts app/build.gradle.kts.bak
        perl -0pi -e 's/isObfuscate\s*=\s*false/isObfuscate = true/g' app/build.gradle.kts
    elif [[ -f "app/build.gradle" ]] && grep -qE 'isObfuscate[[:space:]]*=[[:space:]]*false' app/build.gradle; then
        cp app/build.gradle app/build.gradle.bak
        perl -0pi -e 's/isObfuscate\s*=\s*false/isObfuscate = true/g' app/build.gradle
    fi

    for gradle_file in app/build.gradle.kts app/build.gradle; do
        if [[ -f "$gradle_file" ]] && grep -qE 'isObfuscate[[:space:]]*=[[:space:]]*false' "$gradle_file"; then
            echo "Failed to enable Jerboa R8 class-name obfuscation" >&2
            exit 1
        fi
    done
fi

./gradlew "${GRADLE_ARGS[@]}" clean
./gradlew "${GRADLE_ARGS[@]}" :app:assembleRelease --no-daemon

cp app/build/outputs/apk/release/*release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
