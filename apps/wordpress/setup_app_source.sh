#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/utils.sh"
APK_DIR="${SCRIPT_DIR}/apk"
SIGNED_APK="${APK_DIR}/wordpress.apk"
require_cmd git
require_cmd jq
require_cmd keytool

CODEBASE_DIR="${SCRIPT_DIR}/codebase"
if [[ ! -d "${CODEBASE_DIR}" ]]; then
  fatal "codebase directory not found at ${CODEBASE_DIR}"
fi

safe_cd "${CODEBASE_DIR}"
if [[ ! -f "./gradlew" ]]; then
  fatal "gradlew wrapper not found in codebase"
fi
chmod +x ./gradlew || true

find_apk() {
  find . -type f \( -path "*/release/*/*.apk" -o -path "*/outputs/apk/*/*/*.apk" -o -path "*/outputs/apk/*/*-release-unsigned.apk" \) -print 2>/dev/null | head -n1 || true
}

build_candidates=(
  "assembleRelease"
  "assembleWordpressVanillaRelease"
  "assembleWordpressVanillaDebug"
  "assembleDebug"
)

built_apk=""
for task in "${build_candidates[@]}"; do
  log_info "Attempting Gradle task: ${task}"
  if ./gradlew --no-daemon "${task}" -x lint; then
    built_apk=$(find_apk)
    if [[ -n "${built_apk}" ]]; then
      log_info "Found APK after task ${task}: ${built_apk}"
      break
    fi
  else
    log_warn "Gradle task ${task} failed or produced no APK, continuing"
  fi
done

if [[ -z "${built_apk}" ]]; then
  fatal "No APK produced by gradle"
fi

mkdir -p "${APK_DIR}"
unsigned="${APK_DIR}/unsigned.apk"
cp "${built_apk}" "${unsigned}"

KEYSTORE="${HOME}/.android/debug.keystore"
if [[ ! -f "${KEYSTORE}" ]]; then
  mkdir -p "$(dirname "${KEYSTORE}")"
  keytool -genkeypair -keystore "${KEYSTORE}" -storepass android -keypass android -alias androiddebugkey -dname "CN=Android Debug" -validity 10000 >/dev/null 2>&1 || true
fi

APKSIGNER="$(command -v apksigner || true)"
if [[ -z "${APKSIGNER}" && -n "${ANDROID_HOME:-}" ]]; then
  APKSIGNER="$(ls "${ANDROID_HOME}"/build-tools/*/apksigner 2>/dev/null | head -n1 || true)"
fi

if [[ -n "${APKSIGNER}" && -x "${APKSIGNER}" ]]; then
  log_info "Signing APK with apksigner"
  "${APKSIGNER}" sign --ks "${KEYSTORE}" --ks-pass pass:android --key-pass pass:android --out "${SIGNED_APK}" "${unsigned}" || fatal "apksigner failed"
else
  log_info "Signing APK with jarsigner fallback"
  jarsigner -keystore "${KEYSTORE}" -storepass android -keypass android -signedjar "${SIGNED_APK}" "${unsigned}" androiddebugkey || fatal "jarsigner failed"
fi

rm -f "${unsigned}" || true
if [[ ! -f "${SIGNED_APK}" ]]; then
  fatal "Signed APK not produced at ${SIGNED_APK}"
fi

log_info "Signed APK placed at ${SIGNED_APK}"
