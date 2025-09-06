#!/usr/bin/env bash
set -euo pipefail
UTIL_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="/mobilecybench"
if [[ ! -f "/.dockerenv" ]]; then
    ROOT_DIR="$(git -C "$UTIL_SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"
fi
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
source "$(dirname "${BASH_SOURCE[0]}")/wait.sh"
source "${ROOT_DIR}/tools/host_bridge.sh"


# Checks for required Android tools and SDK presence.
check_android_prereqs() {
    if ! command -v java >/dev/null 2>&1; then
        log_warn "java not found in PATH; building Android apps may fail"
    fi
    if ! command -v adb >/dev/null 2>&1; then
        log_warn "adb not found in PATH; emulator/device connectivity may fail"
    fi
    if [[ -z "${ANDROID_HOME:-}" ]]; then
        log_warn "ANDROID_HOME is not set; Android SDK may be unavailable"
    elif [[ ! -d "${ANDROID_HOME}" ]]; then
        log_warn "ANDROID_HOME is set to ${ANDROID_HOME} but directory does not exist"
    fi
    log_info "Android environment check complete."
    require_cmd java
    require_cmd git
    require_cmd adb
    log_info "Android prerequisites OK"
}

# Starts an Android emulator waits for it to boot.
start_emulator() {
    if adb devices | grep -qE '^emulator-[0-9]+\s+device$'; then
        log_info "Emulator already running. Skipping start."
        return 0
    fi
    log_info "Starting Android emulator..."
    local avd_name=${1:-"Pixel_2_API_28"}
    if [[ -z "$avd_name" ]]; then
        fatal "start_emulator requires AVD name"
    fi
    if [[ -f "/.dockerenv" ]]; then
        log_info "Running in container, starting emulator on host"
        if host_bridge_start; then
            log_info "Emulator started on host"
        else
            fatal "Failed to start emulator on host"
        fi
    else
        local start_script="${ROOT_DIR}/start_emulator.sh"
        if [[ ! -x "$start_script" ]]; then
            fatal "Start emulator script not found/executable at $start_script"
        fi
        "$start_script" "$avd_name" &
        adb wait-for-device
        log_info "Emulator started (AVD=${avd_name})"
    fi
    if ! wait_for_device_boot 120; then
        fatal "Android device did not finish booting within 600s"
    fi
}

# Stops the Android emulator.
stop_emulator() {
    if [[ -f "/.dockerenv" ]]; then
        log_info "Running in container, requesting host to stop emulator"
        if host_bridge_stop; then
            log_info "Stop request sent to host bridge"
        else
            log_warn "Host bridge stop request failed; attempting local/shim fallback"
            if adb emu kill >/dev/null 2>&1; then
                log_info "Sent adb emu kill (fallback)"
            else
                log_warn "adb emu kill fallback failed"
            fi
        fi
    else
        local stop_script="${ROOT_DIR}/stop_emulator.sh"
        if [[ -x "$stop_script" ]]; then
            "$stop_script" || fatal "stop_emulator script failed"
        else
            if adb emu kill >/dev/null 2>&1; then
                log_info "Sent adb emu kill"
            else
                log_warn "adb emu kill failed; emulator may already be stopped"
            fi
        fi
    fi
}

# Installs an APK on the connected Android emulator.
adb_install_apk() {
    local apk_path=$1
    if [[ -z "$apk_path" ]]; then
        fatal "adb_install_apk requires an apk path"
    fi
    if [[ ! -f "$apk_path" ]]; then
        fatal "APK not found at $apk_path"
    fi
    adb install -r "$apk_path"
}

# Launches a specific activity on the Android emulator.
adb_launch_activity() {
    local package_activity=$1
    if [[ -z "$package_activity" ]]; then
        fatal "adb_launch_activity needs component like 'org.package/.MainActivity'"
    fi
    adb shell am start -n "$package_activity" || fatal "Failed to start activity $package_activity"
}

# Computes hashes of files in given directories and outputs JSON.
adb_hash_dirs() {
    if [[ $# -eq 0 ]]; then
        fatal "adb_hash_dirs requires at least one directory"
    fi
    if ! command -v jq >/dev/null 2>&1; then
        fatal "adb_hash_dirs requires 'jq' to build JSON"
    fi
    for d in "$@"; do
        local combined=$(adb shell "find \"$d\" -type f -exec sha256sum {} + 2>/dev/null || true" \
            | awk '{print $1}' | sort | sha256sum | awk '{print $1}' || true)
        jq -n --arg dir "$d" --arg hash "${combined:-}" '{dir:$dir,hash:$hash}'
    done | jq -s 'reduce .[] as $item ({}; . + { ($item.dir): $item.hash }) | {dir_hashes: .}'
}

# Writes a UUID string to secret.txt in each specified device directory and appends UUID string to given file (i.e. secrets.json).
adb_hide_secret_files() {
    local out="${1:-secrets.json}"; shift
    if [[ $# -eq 0 ]]; then
        fatal "At least one directory required"
    fi
    command -v uuidgen >/dev/null 2>&1 || fatal "uuidgen not found"
    command -v jq >/dev/null 2>&1 || fatal "jq not found"
    local uuid=$(uuidgen) || fatal "uuidgen failed"
    local completed=true
    for d in "$@"; do
        local remote="${d%/}/secret.txt"
        adb shell "mkdir -p '${d//\'/\'\\\'\'}'" >/dev/null 2>&1 || log_warn "mkdir failed for $d (may be read-only)"
        if adb shell "echo -n '$uuid' > '$remote'" 2>/dev/null; then
            log_info "Wrote secret to device:$remote"
        else
            completed=false
            log_warn "Failed writing to $remote"
        fi
    done
    if $completed; then
        if [[ -f "$out" ]]; then
            if jq -e 'type == "array"' "$out" >/dev/null 2>&1; then
                jq --arg u "$uuid" '{credentials: ., sandbox: $u}' "$out" > "$out.tmp"
            else
                jq --arg u "$uuid" '. + {sandbox: $u}' "$out" > "$out.tmp"
            fi
            mv "$out.tmp" "$out"
        else
            jq -n --arg u "$uuid" '{sandbox: $u}' > "$out"
        fi
        log_info "Updated sandbox_uuid in $out"
    else
        log_warn "No secrets written; skipping JSON update"
    fi
}

# Choose or create cache volumes
choose_volume() {
    local want="$1" list match
    mapfile -t list < <(docker volume ls --format '{{.Name}}' 2>/dev/null || true)
    for match in "${list[@]}"; do
        if [[ "$match" == *"${want}"* ]]; then
            printf '%s' "$match"
            return 0
        fi
    done
    local new="mobilecybench_${want}"
    docker volume create "$new" >/dev/null 2>&1 || true
    printf '%s' "$new"
}

# Builds an Android app from a submodule source directory inside a build container.
# Arguments:
#   $1 = path to submodule (absolute or relative to ROOT_DIR)
#   $2 = destination path for final APK (host path)
#   $3 = gradle command (e.g., "./gradlew assembleDebug")
#   $4 = OPTIONAL: build container name (default: "mobilecybench-build")
build_app_source() {
    local in_src="$1"
    local dest="$2"
    local gradle_cmd="$3"
    local container_name="${4:-mobilecybench-build}"

    if [[ -z "${in_src:-}" || -z "${dest:-}" || -z "${gradle_cmd:-}" ]]; then
        fatal "build_app_source requires: <src-path> <dest-apk-path> <gradle-cmd> [container-name]"
    fi
    require_cmd docker
    require_cmd tar

    # Resolve host_src (accept absolute or relative to ROOT_DIR)
    local host_src
    if [[ "$in_src" = /* ]]; then
        host_src="$in_src"
    else
        host_src="${ROOT_DIR%/}/${in_src#/}"
    fi

    if [[ ! -d "$host_src" || ! -f "$host_src/gradlew" ]]; then
        fatal "Source missing or gradlew not found at path: $host_src. Initialize submodule on host/orchestrator."
    fi

    # Compute container_src relative to ROOT_DIR
    local rel
    local norm_root="${ROOT_DIR%/}"
    if [[ "$host_src" = "$norm_root" ]]; then
        rel="."
    elif [[ "$host_src" = "$norm_root/"* ]]; then
        rel="${host_src#${norm_root}/}"
    else
        rel="$(basename "$host_src")"
    fi
    local container_src="/mobilecybench/${rel#/}"
    local gradle_vol="$(choose_volume 'gradle-cache')"
    local sdk_vol="$(choose_volume 'android-sdk-cache')"

    # Ensure build container is running
    local started_build=false
    if ! docker ps --format '{{.Names}}' | grep -q -x "$container_name"; then
        if [[ "$container_name" == "mobilecybench-build" ]]; then
            log_info "Attempting: docker compose up -d build"
            if docker compose -f "${ROOT_DIR}/docker-compose.yml" up -d build >/dev/null 2>&1; then
                started_build=true
            else
                log_warn "docker compose up -d build failed; will attempt docker run fallback"
            fi
        fi
    fi

    # docker run fallback (do NOT mount repo root)
    if ! docker ps --format '{{.Names}}' | grep -q -x "$container_name"; then
        local img="$(docker compose -f "${ROOT_DIR}/docker-compose.yml" images -q build 2>/dev/null | head -n1 || true)"
        if [[ -z "$img" ]]; then
            img="$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -m1 '^.*mobilecybench-build' || true)"
        fi
        if [[ -z "$img" ]]; then
            docker images --format 'table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.CreatedSince}}' | sed -n '1,80p' >&2 || true
            fatal "No suitable build image found. Run 'docker compose build' at repo root or start the build container."
        fi

        log_info "docker run fallback: starting container '${container_name}' from image '${img}' (no repo bind mount)"
        docker rm -f "$container_name" >/dev/null 2>&1 || true
        if ! docker run -d --name "$container_name" \
            -v "${gradle_vol}:/root/.gradle" \
            -v "${sdk_vol}:/root/.android-sdk" \
            "${img}" >/tmp/mcb_dockerrun_out.txt 2>/tmp/mcb_dockerrun_err.txt; then
            sed -n '1,200p' /tmp/mcb_dockerrun_err.txt >&2 || true
            fatal "Failed to docker run image ${img} as ${container_name}"
        fi
        started_build=true

        wait_healthy "$container_name" 30
    else
        log_info "Using existing/running container: ${container_name}"
    fi

    # Copy the submodule into container if not present
    if ! docker exec "$container_name" bash -lc "[ -d '${container_src}' ]" >/dev/null 2>&1; then
        log_info "Build container does not expose ${container_src}; copying source in..."
        docker exec "$container_name" mkdir -p "$(dirname "$container_src")" >/dev/null 2>&1 || true
        docker exec "$container_name" bash -lc "rm -rf '${container_src}'" >/dev/null 2>&1 || true

        local host_parent="$(dirname "$host_src")"
        local host_base="$(basename "$host_src")"

        (cd "$host_parent" && tar -c --exclude='.git' "$host_base") | \
          docker exec -i "$container_name" tar -C "$(dirname "$container_src")" -x || {
            log_warn "tar-stream copy failed; attempting docker cp fallback"
            docker cp "$host_src" "${container_name}:${container_src%/*}" || fatal "Failed to copy source into build container"
        }

        if ! docker exec "$container_name" bash -lc "[ -d '${container_src}' ]" >/dev/null 2>&1; then
            fatal "After copy, expected ${container_src} to exist but it does not."
        fi
    else
        log_info "Build container already exposes ${container_src} (via bind-mount), no copy needed."
    fi

    # Ensure aapt2 exists in container before calling Gradle
    if ! docker exec "$container_name" bash -lc "[ -x /usr/bin/aapt2 ]" >/dev/null 2>&1; then
        log_error "Required /usr/bin/aapt2 missing inside ${container_name}. Please ensure fetch_aapt2.sh ran successfully in the image/build container."
        fatal "Missing aapt2 in ${container_name} (/usr/bin/aapt2). You can try: docker exec ${container_name} /usr/local/bin/fetch_aapt2.sh"
    fi
    log_info "Running build inside ${container_name}: cd ${container_src} && ${gradle_cmd}"
    if ! docker exec -u root -w "$container_src" "$container_name" bash -lc "chmod +x ./gradlew 2>/dev/null || true; set -o pipefail; ${gradle_cmd}"; then
        fatal "Gradle build failed (command: ${gradle_cmd}). No automatic fallback attempted."
    fi

    # Find the APK file inside container
    log_info "Searching for APK inside container..."
    local apk_container="$(docker exec "$container_name" bash -lc "sh -lc 'find \"${container_src}\" -type f -path \"*/build/outputs/apk/*/*.apk\" -print0 2>/dev/null | xargs -0 ls -1 -t 2>/dev/null | head -n1'")" || true
    if [[ -z "$apk_container" ]]; then
        apk_container="$(docker exec "$container_name" bash -lc "sh -lc 'find \"${container_src}\" -type f -name \"*.apk\" -print -quit 2>/dev/null'")" || true
    fi
    if [[ -z "$apk_container" ]]; then
        fatal "Could not find built APK in container under ${container_src}"
    fi

    mkdir -p "$(dirname "$dest")"
    docker cp "${container_name}:${apk_container}" "$dest" || fatal "docker cp failed copying ${apk_container} -> $dest"
    log_info "Copied APK from container: ${apk_container} -> $dest"
    return 0
}