#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APK_DIR="${SCRIPT_DIR}/apk"
APK_PATH="${APK_DIR}/simplex-chat.apk"

log()  { printf '[setup_app_apklink] %s\n' "$*"; }
fail() { printf '[setup_app_apklink][error] %s\n' "$*" >&2; exit 1; }

resolve_url() {
  local metadata="${SCRIPT_DIR}/metadata.json"
  [[ -f "$metadata" ]] || fail "metadata.json not found – cannot determine download URL"

  local url
  url=$(python3 -c "import json;print(json.load(open('$metadata')).get('download_link',''))" 2>/dev/null || true)
  [[ -n "$url" ]] || fail "download_link missing from metadata.json"
  echo "$url"
}

download_apk() {
  local url="$1"
  mkdir -p "$APK_DIR"
  log "Downloading APK from $url"
  if command -v curl >/dev/null 2>&1; then
	  echo "Using curl -L ${url} -o ${APK_PATH}"
    curl -L "$url" -o "$APK_PATH"
  elif command -v wget >/dev/null 2>&1; then
	  echo "Using wget -O ${APK_PATH} ${url}"
    wget -O "$APK_PATH" "$url"
  else
    fail "Neither curl nor wget is available"
  fi
}

main() {
  local url
  url=$(resolve_url)

  if [[ -f "$APK_PATH" ]]; then
    log "APK already present at $APK_PATH"
    exit 0
  fi

  download_apk "$url"
  [[ -s "$APK_PATH" ]] || fail "Download failed; APK is empty"
  log "APK ready at $APK_PATH"
}

main "$@"
