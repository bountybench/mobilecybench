#!/usr/bin/env bash
set -euo pipefail

log_info()  { printf '%s\n' "[INFO]  $*"; }
log_warn()  { printf '%s\n' "[WARN]  $*" >&2; }
log_error() { printf '%s\n' "[ERROR] $*" >&2; }
log()  { local tag="$1"; shift || true; printf '%s\n' "[$tag] $*"; }
fatal() {
    local msg="$1"; local rc=${2:-1}
    log_error "$msg"
    exit "$rc"
}
require_cmd() {
    local cmd=$1
    if ! command -v "$cmd" >/dev/null 2>&1; then
        fatal "Required command '$cmd' not found"
    fi
}

TMPDIR="$(mktemp -d)"
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT
ARCH="$(dpkg --print-architecture 2>/dev/null || echo "unknown")"

require_cmd curl
require_cmd tar
require_cmd unzip || true 


# create a consistent, arch-specific /usr/lib/jvm/java-17-openjdk symlink
make_java_symlink() {
    case "$ARCH" in
        amd64)
        if [ -d /usr/lib/jvm/java-17-openjdk-amd64 ]; then
            ln -sf /usr/lib/jvm/java-17-openjdk-amd64 /usr/lib/jvm/java-17-openjdk
            log_info "Linked /usr/lib/jvm/java-17-openjdk -> java-17-openjdk-amd64"
        else
            log_warn "Warning: expected /usr/lib/jvm/java-17-openjdk-amd64 does not exist"
        fi
        ;;
        arm64)
        if [ -d /usr/lib/jvm/java-17-openjdk-arm64 ]; then
            ln -sf /usr/lib/jvm/java-17-openjdk-arm64 /usr/lib/jvm/java-17-openjdk
            log_info "Linked /usr/lib/jvm/java-17-openjdk -> java-17-openjdk-arm64"
        else
            log_warn "Warning: expected /usr/lib/jvm/java-17-openjdk-arm64 does not exist"
        fi
        ;;
        *)
        log_warn "Unknown architecture: $ARCH - skipping java symlink"
        ;;
    esac
}

download_file() {
  local url="$1"
  local out="$2"
  log_info"curl -> $url"
  curl -fSL --retry 2 --retry-delay 1 -o "$out" "$url"
}

extract_and_install_aapt2() {
    local pkg="$1"
    mkdir -p /usr/bin
    case "$pkg" in
        *.zip)
            unzip -q "$pkg" -d "$TMPDIR/extracted"
            ;;
        *.tar.xz|*.txz)
            tar -xJf "$pkg" -C "$TMPDIR/extracted"
            ;;
        *.tar.gz|*.tgz)
            tar -xzf "$pkg" -C "$TMPDIR/extracted"
            ;;
        *)
            if mv "$pkg" /usr/bin/aapt2 2>/dev/null || cp -f "$pkg" /usr/bin/aapt2 2>/dev/null; then
                chmod +x /usr/bin/aapt2
                log_info"Installed /usr/bin/aapt2 (single-file)"
                return 0
            else
                return 1
            fi
            ;;
    esac

    # look for an aapt2 binary in extracted tree
    local found="$(find "$TMPDIR/extracted" -type f -name aapt2 -print -quit || true)"
    if [ -n "$found" ]; then
        mv "$found" /usr/bin/aapt2
        chmod +x /usr/bin/aapt2
        log_info "Installed /usr/bin/aapt2 from archive"
        return 0
    fi
    found="$(find "$TMPDIR/extracted" -type f -path '*/build-tools/*/aapt2' -print -quit || true)"
    if [ -n "$found" ]; then
        mv "$found" /usr/bin/aapt2
        chmod +x /usr/bin/aapt2
        log_info "Installed /usr/bin/aapt2 from build-tools path inside archive"
        return 0
    fi
    return 1
}

install_from_jar() {
    local jar="$1"
    local extr="$(mktemp -d "${TMPDIR}/extracted.XXXX")"
    unzip -o -q "$jar" -d "$extr"
    local cand="$(find "$extr" -type f \( -name 'aapt2' -o -iname '*aapt2*' \) -print -quit || true)"
    if [ -z "$cand" ]; then
        log_warn "No aapt2 file found inside $jar; listing a few extracted files for debugging:"
        find "$extr" -maxdepth 3 -type f -print | sed -n '1,40p' >&2 || true
        rm -rf "$extr"
        return 1
    fi
    mkdir -p /usr/bin
    cp -f "$cand" /usr/bin/aapt2
    chmod +x /usr/bin/aapt2
    if [ -f /usr/bin/aapt2 ]; then
        rm -rf "$extr"
        log_info "Installed /usr/bin/aapt2 from $jar (source: $cand)"
        return 0
    else
        log_warn "Candidate $cand was not installed properly."
        rm -f /usr/bin/aapt2 || true
        rm -rf "$extr"
        return 1
    fi
}

amd64_install() {
    log_info "Attempting direct download of official aapt2 linux/amd64"
    local url="https://dl.google.com/dl/android/maven2/com/android/tools/build/aapt2/8.12.2-13700139/aapt2-8.12.2-13700139-linux.jar"
    local out="${TMPDIR}/aapt2-fixed.jar"
    log_info "curl -> $url"
    curl -fSL --retry 2 --retry-delay 1 -o "$out" "$url"
    if install_from_jar "$out"; then
        return 0
    fi
    fatal "Failed to install aapt2 from fixed URL: $url"
}

arm64_install() {
    local urls=(
        "https://github.com/lzhiyong/android-sdk-tools/releases/download/35.0.2/android-sdk-tools-static-aarch64.zip"
        "https://github.com/lzhiyong/android-sdk-tools/releases/download/34.0.3/android-sdk-tools-static-aarch64.zip"
        "https://github.com/AndroidIDEOfficial/platform-tools/releases/download/v34.0.4/platform-tools-34.0.4-aarch64.tar.xz"
        "https://github.com/rendiix/termux-aapt/releases/download/termux-sdk-tools-34.0.0/termux-sdk-tools-34.0.0.tar.xz"
    )
    for u in "${urls[@]}"; do
        local out="${TMPDIR}/pkg.$(basename "$u")"
        if download_file "$u" "$out"; then
            if extract_and_install_aapt2 "$out"; then
                log_info "aapt2 installed from community URL: $u"
                return 0
            else
                log_info "Downloaded package from $u but could not find aapt2 inside"
            fi
        else
            log_warn "Download failed for $u"
        fi
    done
    return 1
}

main() {
    log_info "Starting fetch_aapt2 (arch: $ARCH)"
    make_java_symlink
    if [ -x /usr/bin/aapt2 ]; then
        log_info "/usr/bin/aapt2 already present - skipping download"
        exit 0
    fi

    case "$ARCH" in
        amd64)
        amd64_install
        ;;
        arm64|aarch64)
        arm64_install
        ;;
        *)
        fatal "Unsupported or unknown arch: $ARCH"
        ;;
    esac
    if [ ! -x /usr/bin/aapt2 ]; then
        fatal "aapt2 was not installed successfully."
    fi
    log_info "aapt2 installed and ready at /usr/bin/aapt2"
}

main "$@"