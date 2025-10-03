#!/usr/bin/env bash
set -euo pipefail

LOG() { printf "%s
" "$*" >&2; }
ERR() { printf "ERROR: %s
" "$*" >&2; exit 1; }

MODULE_NAME="${1:-openhab}"
FORCE="${FORCE:-false}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
METADATA_FILE="$ROOT_DIR/metadata.json"

usage() {
  cat <<EOF
Usage: $0 [MODULE_NAME]

Fetches the APK set in metadata.json:download_link and writes it to
  /apk/openhab.apk

Environment:
  MODULE_NAME - override app name (default: mobile)
  DOWNLOAD_LINK - optional URL override
  FORCE - if true, re-download even if file exists

EOF
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  usage
  exit 0
fi

if [ ! -f "$METADATA_FILE" ] && [ -z "${DOWNLOAD_LINK:-}" ]; then
  ERR "metadata.json not found at $METADATA_FILE and DOWNLOAD_LINK not set"
fi

get_download_link() {
  if [ -n "${DOWNLOAD_LINK:-}" ]; then
    printf "%s" "$DOWNLOAD_LINK"
    return 0
  fi

  # Try python3 then python for robust JSON parsing
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["download_link"])' "$METADATA_FILE"
    return 0
  elif command -v python >/dev/null 2>&1; then
    python -c 'import json,sys;print(json.load(open(sys.argv[1]))["download_link"])' "$METADATA_FILE"
    return 0
  else
    # Fallback to grep/sed (best-effort)
    grep -o '"download_link"[[:space:]]*:[[:space:]]*"[^"]\+"' "$METADATA_FILE" | sed -E 's/.*:"([^"]+)"/\1/' || true
    return 0
  fi
}

DOWNLOAD_URL="$(get_download_link)"

if [ -z "$DOWNLOAD_URL" ]; then
  ERR "Could not determine download link from metadata or env"
fi

DEST_DIR="$ROOT_DIR/apk"
DEST_PATH="$DEST_DIR/openhab.apk"

mkdir -p "$DEST_DIR"

if [ -f "$DEST_PATH" ] && [ "$FORCE" != "true" ]; then
  LOG "Destination $DEST_PATH already exists. Use FORCE=true to overwrite. Skipping download."
  exit 0
fi

download_with_curl() {
  # -f : fail on HTTP errors
  # -L : follow redirects
  # -S : show errors
  # -o : output file
  curl -fSL "$DOWNLOAD_URL" -o "$DEST_PATH"
}

download_with_wget() {
  wget -O "$DEST_PATH" "$DOWNLOAD_URL"
}

LOG "Downloading APK from: $DOWNLOAD_URL"

if command -v curl >/dev/null 2>&1; then
  if download_with_curl; then
    LOG "Downloaded to $DEST_PATH"
    exit 0
  else
    LOG "curl failed, trying wget"
  fi
fi

if command -v wget >/dev/null 2>&1; then
  if download_with_wget; then
    LOG "Downloaded to $DEST_PATH"
    exit 0
  else
    ERR "wget failed to download $DOWNLOAD_URL"
  fi
fi

ERR "Neither curl nor wget available to download $DOWNLOAD_URL"
