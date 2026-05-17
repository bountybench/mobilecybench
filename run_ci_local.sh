#!/bin/bash

# Define color codes
GREEN="\033[1;32m"
RED="\033[1;31m"
YELLOW="\033[1;33m"
CYAN="\033[1;36m"
RESET="\033[0m"

# Define message prefixes
INFO="${CYAN}[INFO]${RESET}"
SUCCESS="${GREEN}[SUCCESS]${RESET}"
ERROR="${RED}[ERROR]${RESET}"
WARNING="${YELLOW}[WARNING]${RESET}"

ROOT_DIR=$(pwd)
PYTHON_CMD=$("${ROOT_DIR}/utils/detect_python.sh") || exit 1
source "${ROOT_DIR}/utils/android.sh"
source "${ROOT_DIR}/utils/wait.sh"
source "${ROOT_DIR}/utils/local_error_logger.sh"
source "${ROOT_DIR}/scripts/task_validation_common.sh"
source "${ROOT_DIR}/scripts/zero_day_task_common.sh"
set +e

DIR=""

print_header() {
    local color="$1"
    local message="$2"
    echo -e "${color}========== ${message} ==========${RESET}"
}

print_error_header() {
    local message="$1"
    echo -e "${ERROR} ${message} ==========${RESET}" >&2
}

check_metadata_schema() {
    local metadata_file="$1"
    echo "Checking metadata.json against expected schema..."

    if ! jq empty "$metadata_file" >/dev/null 2>&1; then
        print_error_header "[FAIL] Invalid JSON in $metadata_file"
        echo -e "${ERROR} The metadata.json file contains invalid JSON syntax."
        exit 1
    fi

    local required_fields=(
        "gh_link:GitHub link to the app's repository"
        "commit_version:Commit version to checkout for testing"
        "sdk:Android SDK version required"
        "java:Java version needed to compile the app"
        "package_name:Package name of the Android app"
        "app_server:Address of any server the app requires (empty string if not required)"
        "container_names:Array of Docker container names for health checks (empty array if not required)"
    )
    all_passed=true

    for field_pair in "${required_fields[@]}"; do
        field="${field_pair%%:*}"
        description="${field_pair#*:}"

        if jq -e ".${field}" "$metadata_file" >/dev/null 2>&1; then
            print_header "$GREEN" "[PASS] Attribute $field is in the metadata."
        else
            print_error_header "[FAIL] Attribute $field is not in the metadata."
            print_error_header " --> Attribute ${description} is not in the metadata."
            all_passed=false
        fi
    done

    if [ "$all_passed" = true ]; then
        print_header "$GREEN" "[PASS] Metadata schema validation success."
    else
        print_error_header "[FAIL] Metadata schema validation failed."
        exit 1
    fi
}

check_app_containers_ready() {
    if ! task_validation_check_app_containers_ready "$(pwd)/metadata.json"; then
        exit 1
    fi
}

verify_shared_net_connectivity() {
    # Verify shared_net connectivity after containers are started
    echo "Verifying shared_net connectivity..."
    if [ -f "metadata.json" ]; then
        app_server=$(jq -r '.app_server // empty' "metadata.json")
        if [ -n "$app_server" ]; then
            echo "Testing connectivity to: $app_server"
            
            # Strip protocol prefix if present (http://, https://)
            server_clean=$(echo "$app_server" | sed 's|^[^:]*://||')
            echo "  Raw app_server: $app_server"
            echo "  Cleaned server: $server_clean"
            
            # Parse host and port - require explicit port
            if [[ "$server_clean" == *":"* ]]; then
                host=$(echo "$server_clean" | cut -d':' -f1)
                port=$(echo "$server_clean" | cut -d':' -f2)
                echo "  Parsed host: $host"
                echo "  Parsed port: $port"
            else
                echo "ERROR: No port specified in app_server: $app_server"
                exit 1
            fi
            
            echo "  Testing connection to $host:$port via shared_net..."
            docker run --rm --network=shared_net alpine:latest \
                sh -c "nc -z -w 30 $host $port || (echo 'ERROR: Cannot reach app server via shared_net' && exit 1)"

            echo "shared_net connectivity verified"
        else
            echo "No app_server defined in metadata.json, skipping connectivity check"
        fi
    else
        echo "No metadata.json found, skipping connectivity check"
    fi
}

compare_expected_score_subset() {
    local expected_json="$1"
    local actual_json="$2"
    python3 "$ROOT_DIR/scripts/compare_score_subset.py" "$expected_json" "$actual_json"
}

# Start SSRF listener container
start_ssrf_listener() {
    echo -e "${INFO} Starting SSRF listener container..."
    local ssrf_compose_dir="${ROOT_DIR}/evaluation/ssrf_listener"
    
    if [ ! -d "$ssrf_compose_dir" ]; then
        echo -e "${WARNING} SSRF listener directory not found at $ssrf_compose_dir"
        return 1
    fi
    
    # Stop any existing SSRF listener
    docker compose -f "$ssrf_compose_dir/docker-compose.yml" down -v 2>/dev/null || true
    
    # Build and start the SSRF listener
    if docker compose -f "$ssrf_compose_dir/docker-compose.yml" up -d --build --wait; then
        echo -e "${SUCCESS} SSRF listener started on port 14377"
        return 0
    else
        echo -e "${WARNING} Failed to start SSRF listener"
        return 1
    fi
}

# Stop SSRF listener container
stop_ssrf_listener() {
    echo -e "${INFO} Stopping SSRF listener container..."
    local ssrf_compose_dir="${ROOT_DIR}/evaluation/ssrf_listener"
    
    if [ -d "$ssrf_compose_dir" ]; then
        docker compose -f "$ssrf_compose_dir/docker-compose.yml" down -v 2>/dev/null || true
    fi
    
    # Also try to stop container directly in case compose fails
    docker stop ssrf-probe 2>/dev/null || true
    docker rm -f ssrf-probe 2>/dev/null || true
    
    echo -e "${INFO} SSRF listener stopped"
}

# Clear SSRF request log
clear_ssrf_requests() {
    echo -e "${INFO} Clearing SSRF request log..."
    docker exec ssrf-probe rm -f /app/logs/ssrf_requests.json 2>/dev/null || true
}

# Validate directory structure and required scripts
validate_setup_app_scripts() {
    local dir="$1"

    if [ ! -d "$dir" ]; then
        echo -e "${ERROR} Directory '$dir' does not exist" >&2
        return 1
    fi

    local has_build_script=false
    local has_download_link=false

    if [ -f "$dir/build.sh" ]; then
        has_build_script=true
    fi

    if [ -f "$dir/metadata.json" ]; then
        download_link=$(jq -r '.download_link // empty' "$dir/metadata.json")
        if [ -n "$download_link" ]; then
            has_download_link=true
        fi
    fi

    if [ "$has_build_script" = false ] && [ "$has_download_link" = false ]; then
        echo -e "${ERROR} No setup options found in $dir" >&2
        echo -e "${ERROR} Expected: build.sh or download_link in metadata.json" >&2
        return 1
    fi
    return 0
}


discover_available_modes() {
    local dir="$1"
    local modes=""

    # If --skip-apk is specified, only offer apk_skip mode
    if [ "$SKIP_APK" = true ]; then
        modes="apk_skip"
        echo -e "${INFO} --skip-apk specified - using apk_skip mode" >&2
    else
        if [ -f "$dir/build.sh" ]; then
            modes="$modes source"
            echo -e "${INFO} Found build.sh (build mode)" >&2
        fi
        if [ -f "$dir/metadata.json" ]; then
            download_link=$(jq -r '.download_link // empty' "$dir/metadata.json")
            if [ -n "$download_link" ]; then
                modes="$modes apklink"
                echo -e "${INFO} Found download_link in metadata.json (download mode)" >&2
            fi
        fi
    fi

    echo "$modes"
}

filter_modes_by_flags() {
    local available_modes="$1"
    local filtered_modes=""
    
    for mode in $available_modes; do
        case "$mode" in
            "source")
                if [ "$SKIP_BUILD" != true ]; then
                    filtered_modes="$filtered_modes $mode"
                else
                    echo -e "${INFO} Skipping build mode (source) due to --skip-build flag" >&2
                fi
                ;;
            "apklink")
                if [ "$SKIP_DOWNLOAD" != true ]; then
                    filtered_modes="$filtered_modes $mode"
                else
                    echo -e "${INFO} Skipping download mode (apklink) due to --skip-download flag" >&2
                fi
                ;;
            "apk_skip")
                filtered_modes="$filtered_modes $mode"
                echo -e "${INFO} Using apk_skip mode - will re-use existing APK if available" >&2
                ;;
        esac
    done
    
    # Trim leading/trailing spaces
    echo "$filtered_modes" | sed 's/^ *//;s/ *$//'
}

# Main function to determine setup modes
determine_setup_modes() {
    local dir="$1"

    if ! validate_setup_app_scripts "$dir"; then
        exit 1
    fi
    
    local available_modes
    available_modes=$(discover_available_modes "$dir")
    echo -e "${INFO} Available setup modes: $available_modes" >&2
    
    local selected_modes
    selected_modes=$(filter_modes_by_flags "$available_modes")

    # will fail if no mode is left after user filter
    if [ -z "$selected_modes" ]; then
        echo -e "${ERROR} No setup modes available after applying filters" >&2
        echo -e "${ERROR} Available modes were: $available_modes" >&2
        echo -e "${ERROR} Try removing --skip-* flags or ensure required scripts exist" >&2
        exit 1
    fi
    
    local mode_count
    mode_count=$(echo "$selected_modes" | wc -w)
    if [ "$mode_count" -eq 1 ]; then
        echo -e "${INFO} Selected setup mode: $selected_modes" >&2
    else
        echo -e "${INFO} Selected setup modes: $selected_modes (running both by default)" >&2
    fi
    
    echo "$selected_modes"
}

current_app_dir() {
    local app_dir
    app_dir=$(git rev-parse --show-prefix 2>/dev/null || true)
    app_dir="${app_dir%/}"

    if [[ -z "$app_dir" || "$app_dir" != apps/* ]]; then
        echo -e "${ERROR} Could not determine app directory from current directory: $(pwd)" >&2
        return 1
    fi

    echo "$app_dir"
}

init_app_submodules() {
    local app_dir="${1:-}"
    if [[ -z "$app_dir" ]]; then
        app_dir=$(current_app_dir) || return 1
    fi
    app_dir="${app_dir%/}"

    local app_prefix="${app_dir}/"
    local submodule_paths=()
    while IFS= read -r submodule_path; do
        [[ -n "$submodule_path" ]] && submodule_paths+=("$submodule_path")
    done < <(
        git -C "$ROOT_DIR" config -f .gitmodules \
            --get-regexp '^submodule\..*\.path$' 2>/dev/null \
            | awk -v prefix="$app_prefix" 'index($2, prefix) == 1 { print $2 }' \
            || true
    )

    if [[ ${#submodule_paths[@]} -eq 0 ]]; then
        echo -e "${ERROR} No submodules registered under ${app_prefix} in .gitmodules" >&2
        return 1
    fi

    # Initialize every submodule registered under the app, not just codebase.
    # Some apps ship auxiliary runtime submodules (for example Jitsi Docker
    # assets) that start_runtime.sh needs, but only codebase is checked out to
    # the app commit below.
    for submodule_path in "${submodule_paths[@]}"; do
        echo -e "${INFO} Initializing submodule: ${submodule_path}"
        if ! git -C "$ROOT_DIR" submodule update --init "$submodule_path"; then
            echo -e "${ERROR} Failed to initialize submodule: ${submodule_path}" >&2
            return 1
        fi
    done
}

checkout_commit() {
    local commit_override="${1:-}"
    echo "Current directory: $(pwd)"
    if [[ -f "metadata.json" ]]; then
        local commit="$commit_override"
        if [[ -z "$commit" ]]; then
            commit=$(jq -r '.["commit_version"] // empty' "metadata.json")
        fi

        if [[ -n "$commit" ]]; then
            echo "Found commit: $commit"

            init_app_submodules || exit 1
            echo "Cleaning repository to remove all changes and untracked files..."

            cd "codebase" || exit 1

            echo "Cleaning up the codebase"
            git reset --hard HEAD
            git clean -fdx

            # Update the submodule and checkout the commit
            git checkout "$commit"

            cd - || exit 1
        else
            echo "No commit version found in metadata.json"
            exit 1
        fi
    else
        echo "No metadata.json file found"
        exit 1
    fi
}

# Apply a vulnerability patch to the codebase
apply_vulnerability_patch() {
    local patch_file="$1"
    
    echo -e "${INFO} Applying vulnerability patch: $patch_file"
    
    if [ ! -f "$patch_file" ]; then
        echo -e "${ERROR} Patch file not found: $patch_file"
        return 1
    fi
    
    cd "codebase" || return 1
    
    if git apply --check "$patch_file" 2>&1; then
        echo -e "${INFO} Patch validation successful"
        if git apply "$patch_file"; then
            echo -e "${SUCCESS} Patch applied successfully"
            cd - || return 1
            return 0
        else
            echo -e "${ERROR} Failed to apply patch"
            cd - || return 1
            return 1
        fi
    else
        echo -e "${ERROR} Patch validation failed"
        cd - || return 1
        return 1
    fi
}

load_vuln_test_settings() {
    local vuln_dir="$1"
    local app_dir="$2"

    VULN_METADATA_FILE="$ROOT_DIR/$app_dir/$vuln_dir/metadata.json"
    if [ ! -f "$VULN_METADATA_FILE" ]; then
        echo -e "${ERROR} metadata.json not found: $VULN_METADATA_FILE"
        return 1
    fi

    VULN_BASELINE_COMMIT=$(jq -r '.baseline.commit // empty' "$VULN_METADATA_FILE")
    VULN_TASK_ID=$(jq -r '.task_id // .task_slug // empty' "$VULN_METADATA_FILE")
    VULN_PACKAGE_NAME=$(jq -r '.runtime.package_name // .app_metadata_overrides.package_name // empty' "$VULN_METADATA_FILE")
    VULN_ATTACKER_MODEL=$(jq -r '.attacker_model // empty' "$VULN_METADATA_FILE")
    case "$VULN_ATTACKER_MODEL" in
        malicious_app|remote_attacker) ;;
        "")
            echo -e "${ERROR} metadata.json missing attacker_model (expected: malicious_app, remote_attacker): $VULN_METADATA_FILE"
            return 1
            ;;
        *)
            echo -e "${ERROR} metadata.json attacker_model=\"$VULN_ATTACKER_MODEL\" is invalid (expected: malicious_app, remote_attacker): $VULN_METADATA_FILE"
            return 1
            ;;
    esac
    if [ -z "$VULN_PACKAGE_NAME" ] || [ "$VULN_PACKAGE_NAME" = "null" ]; then
        VULN_PACKAGE_NAME=$(jq -r '.package_name // empty' "$ROOT_DIR/$app_dir/metadata.json")
    fi
    if [ -z "$VULN_PACKAGE_NAME" ] || [ "$VULN_PACKAGE_NAME" = "null" ]; then
        echo -e "${ERROR} Failed to resolve package_name for $vuln_dir"
        return 1
    fi

    VULN_BUILD_ENV_ARGS=()
    while IFS=$'	' read -r key value; do
        [ -n "$key" ] || continue
        VULN_BUILD_ENV_ARGS+=("$key=$value")
    done < <(
        jq -r '(.build.env // .build_env // {}) | to_entries[]? | [.key, (.value | tostring)] | @tsv'             "$VULN_METADATA_FILE"
    )

    return 0
}

run_build_apk_with_vuln_env() {
    local app_name="$1"
    shift
    local -a build_args=("$@")

    if [ -n "${VULN_BASELINE_COMMIT:-}" ] && [ "$VULN_BASELINE_COMMIT" != "null" ]; then
        build_args=(--commit "$VULN_BASELINE_COMMIT" "${build_args[@]}")
    fi

    if [ ${#VULN_BUILD_ENV_ARGS[@]} -gt 0 ]; then
        env "${VULN_BUILD_ENV_ARGS[@]}" ./build_apk.sh "$app_name" "${OBFUSCATE_BUILD_FLAG[@]}" "${build_args[@]}"
    else
        ./build_apk.sh "$app_name" "${OBFUSCATE_BUILD_FLAG[@]}" "${build_args[@]}"
    fi
}

SYNTH_RUNTIME_PATCH_FILE=""

synthetic_phase_apply_vulnerability_patch() {
    if [ -z "$SYNTH_RUNTIME_PATCH_FILE" ]; then
        echo -e "${ERROR} Synthetic runtime patch file is not set"
        return 1
    fi
    echo -e "${INFO} Applying synthetic vulnerability patch for runtime services..."
    apply_vulnerability_patch "$SYNTH_RUNTIME_PATCH_FILE"
}

run_zero_day_task() {
    local task_dir="$1"
    local app_dir="$2"

    # Local public zero-day tasks use the same shared runner as external ones.
    print_header "$CYAN" "TESTING ZERO-DAY TASK: $task_dir"

    local app_name
    app_name=$(basename "$app_dir")
    local task_abs_path="$ROOT_DIR/$app_dir/$task_dir"

    if [ ! -d "$task_abs_path" ]; then
        echo -e "${ERROR} Task directory not found: $task_abs_path"
        exit 1
    fi

    start_emulator_and_adb

    if ! zero_day_task_run_validation "$app_name" "$task_abs_path" "$SKIP_APK" "" "false"; then
        exit 1
    fi
}

# Parse command line arguments
SKIP_BUILD=false
SKIP_DOWNLOAD=false
SKIP_APK=false
RUN_UNIT_TESTS=false
TEST_SYNTHETIC_VULN=""
TEST_ZERO_DAY_VULN=""
TEST_ALL_SYNTHETIC_VULNS=false
OBFUSCATE=false  # When true, build/download the R8-minified APK variant
OBFUSCATE_BUILD_FLAG=()      # Appended to ./build_apk.sh   when OBFUSCATE=true
OBFUSCATE_DOWNLOAD_FLAG=()   # Appended to download_apk.py  when OBFUSCATE=true
VULN_METADATA_FILE=""
VULN_CLEAN_APK_MODE="default"
VULN_TASK_ID=""
VULN_BASELINE_COMMIT=""
VULN_PACKAGE_NAME=""
VULN_ATTACKER_MODEL=""
declare -a VULN_BUILD_ENV_ARGS=()

show_usage() {
    echo "Usage: $0 <dir> [options]"
    echo ""
    echo "Arguments:"
    echo "  <dir>             Directory to test (e.g., apps/joplin)"
    echo ""
    echo "Options:"
    echo "  --skip-build      Skip build mode (source setup)"
    echo "  --skip-download   Skip download mode (apklink setup)"
    echo "  --skip-apk        Skip building APK. Use existing APK or download from metadata download_link."
    echo "  --unit-tests      Run unit tests (opt-in)"
    echo "  --test-synthetic-vuln <vuln_dir>"
    echo "                    Test a synthetic vulnerability (e.g., synthetic_vulnerabilities/vuln_0)"
    echo "  --test-zero-day-vuln <vuln_dir>"
    echo "                    Test a zero-day vulnerability task (e.g., zero_day_vulnerabilities/location_spoofing)"
    echo "  --test-all-synthetic-vulns"
    echo "                    Test all synthetic vulnerabilities found in synthetic_vulnerabilities/"
    echo "  --obfuscate       Build/download the R8-minified APK variant (mirrors CI's"
    echo "                    obfuscated matrix; routes APKs to apk/obfuscated/ and"
    echo "                    plumbs --obfuscate to build_apk.sh / --obfuscated to download_apk.py)"
    echo "  -h, --help        Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 apps/joplin                   # Run both build and download modes"
    echo "  $0 apps/joplin --skip-build      # Run only download mode"
    echo "  $0 apps/joplin --skip-download   # Run only build mode"
    echo "  $0 apps/joplin --skip-apk        # Use existing APK or download if missing"
    echo "  $0 apps/joplin --unit-tests      # Run unit tests"
    echo "  $0 apps/conversations --test-synthetic-vuln synthetic_vulnerabilities/vuln_0"
    echo "                                   # Test synthetic vulnerability"
    echo "  $0 apps/home-assistant-android --test-zero-day-vuln zero_day_vulnerabilities/location_spoofing"
    echo "                                   # Test zero-day vulnerability task"
    echo "  $0 apps/conversations --test-all-synthetic-vulns"
    echo "                                   # Test all synthetic vulnerabilities"
    echo ""
    echo "By default, both build mode (source) and download mode (apklink) are run"
    echo "when both setup scripts are available."
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --skip-download)
            SKIP_DOWNLOAD=true
            shift
            ;;
        --skip-apk)
            SKIP_APK=true
            SKIP_BUILD=true
            SKIP_DOWNLOAD=true
            shift
            ;;
        --unit-tests)
            RUN_UNIT_TESTS=true
            shift
            ;;
        --test-synthetic-vuln)
            if [ -z "$2" ] || [[ "$2" == -* ]]; then
                echo "Error: --test-synthetic-vuln requires a vulnerability directory argument"
                show_usage
                exit 1
            fi
            TEST_SYNTHETIC_VULN="$2"
            shift 2
            ;;
        --test-zero-day-vuln)
            if [ -z "$2" ] || [[ "$2" == -* ]]; then
                echo "Error: --test-zero-day-vuln requires a vulnerability directory argument"
                show_usage
                exit 1
            fi
            TEST_ZERO_DAY_VULN="$2"
            shift 2
            ;;
        --test-all-synthetic-vulns)
            TEST_ALL_SYNTHETIC_VULNS=true
            shift
            ;;
        --obfuscate)
            OBFUSCATE=true
            OBFUSCATE_BUILD_FLAG=(--obfuscate)
            OBFUSCATE_DOWNLOAD_FLAG=(--obfuscated)
            # Export so child processes (start_runtime.sh sourcing
            # utils/android.sh, parse_apk_path) route the default APK lookup
            # to apk/obfuscated/<app>.apk. Mirrors CI's test_checks.sh.
            export MCB_OBFUSCATE=1
            shift
            ;;
        -h|--help)
            show_usage
            exit 0
            ;;
        -*)
            echo "Unknown option: $1"
            show_usage
            exit 1
            ;;
        *)
            if [ -z "$DIR" ]; then
                DIR="$1"
            else
                echo "Multiple directories specified. Only one directory allowed."
                show_usage
                exit 1
            fi
            shift
            ;;
    esac
done

# Check if directory was provided
if [ -z "$DIR" ]; then
    echo "Error: Directory argument is required"
    echo ""
    show_usage
    exit 1
fi

# Validate flag combination
if [ "$SKIP_BUILD" = true ] && [ "$SKIP_DOWNLOAD" = true ] && [ "$SKIP_APK" != true ]; then
    echo "Error: Cannot skip both build and download modes (use --skip-apk to skip all APK operations)"
    echo ""
    show_usage
    exit 1
fi

# Get API level from metadata
print_header "$CYAN" "GETTING SDK INFORMATION"
metadata="$DIR/metadata.json"
if [ ! -f "$metadata" ]; then
    echo -e "${ERROR} $metadata not found"
    exit 1
fi
check_metadata_schema "$metadata"

# Enforce CI parity: CI never emits obfuscated jobs unless apk_obfuscation
# is in {default, force_on, upstream_forced}. Fail-fast locally so a passing
# local run can't diverge from what CI would actually exercise.
if [ "$OBFUSCATE" = true ]; then
    # CI parity: synthetic_vuln is not emitted in the obfuscated matrix
    # because vulnerability.patch + R8 interactions produce false-negative
    # exploit failures unrelated to agent capability. See
    # documentation/SYNTHETIC_VULNERABILITIES.md for the rationale and the
    # per-vuln keep-rules escape hatch.
    if [ -n "$TEST_SYNTHETIC_VULN" ] || [ "$TEST_ALL_SYNTHETIC_VULNS" = true ]; then
        echo -e "${ERROR} --obfuscate cannot be combined with --test-synthetic-vuln"
        echo -e "${ERROR} or --test-all-synthetic-vulns. Synthetic-vuln tests are excluded"
        echo -e "${ERROR} from the obfuscated CI matrix because R8 may inline lambdas,"
        echo -e "${ERROR} strip debug logs, or rename reflection-discovered methods in ways"
        echo -e "${ERROR} that break the vulnerability.patch's observable side effect."
        echo -e "${ERROR} See documentation/SYNTHETIC_VULNERABILITIES.md for details."
        exit 1
    fi

    apk_obfuscation_meta=$(jq -r '.apk_obfuscation // ""' "$metadata")
    case "$apk_obfuscation_meta" in
        default|force_on|upstream_forced)
            echo -e "${INFO} --obfuscate: app opted in (apk_obfuscation='$apk_obfuscation_meta')"
            ;;
        *)
            echo -e "${ERROR} --obfuscate passed but $DIR/metadata.json apk_obfuscation"
            echo -e "${ERROR} is '${apk_obfuscation_meta:-<unset>}'. CI would not emit obfuscated"
            echo -e "${ERROR} jobs for this app. Set apk_obfuscation to one of:"
            echo -e "${ERROR}   default | force_on | upstream_forced"
            echo -e "${ERROR} in metadata.json before running with --obfuscate."
            exit 1
            ;;
    esac
fi

sdk=$(jq -r '.sdk' "$metadata")
if [ "$?" -ne 0 ] || [ "$sdk" = "null" ] || [ -z "$sdk" ]; then
    echo -e "${ERROR} Could not extract SDK from $metadata."
    exit 1
else 
    echo -e "${INFO} SDK: $sdk"
fi

print_header "$CYAN" "STARTING LOCAL CIA TESTS"

START_TIME=$(date +%s)

#Define Function to uninstall package if not already done by cleanup.sh
uninstall_package() {
    package_name="$1"

    if adb shell pm list packages | grep -q "^package:$package_name$"; then
        echo "NOTICE: Package $package_name is currently installed. Please uninstall your app in cleanup.sh. Proceeding to uninstall automatically..."
        adb uninstall "$package_name" >/dev/null 2>&1

        #still exists after attempt at uninstall
        if adb shell pm list packages | grep -q "^package:$package_name$"; then
            echo "ERROR: Failed to uninstall package $package_name"
            exit 1
        else
            echo "SUCCESS: Package $package_name has been successfully uninstalled"
        fi
    fi
}

# Run prepare_victim.sh when the app provides one. Invoked after
# inject_flags.sh so post-login baselines reflect the flag-injected app
# state, mirroring redteam's _restart_runtime(inject_flags=...) →
# _run_prepare_victim() ordering.
# Bails on failure: missing victim setup = probes operate on wrong state.
run_prepare_victim_if_applicable() {
    if [ ! -x "./prepare_victim.sh" ]; then
        echo -e "${INFO} No prepare_victim.sh in $(pwd); skipping"
        return 0
    fi
    echo -e "${INFO} Running prepare_victim.sh..."
    ./prepare_victim.sh || { echo -e "${ERROR} prepare_victim.sh failed"; return 1; }
}

# Function to run test checks
run_test_check() {
    local test_name="$1"
    local vuln_scenario="$2"
    local use_fake_agent_log="$3"

    print_header "$CYAN" "RUNNING $test_name"

    cd "$ROOT_DIR"
    cd "$DIR"

    # Clear SSRF requests before each test
    clear_ssrf_requests

    # Get package_name from metadata.json (required field) and verify before setup
    package_name=$(jq -r '.package_name' metadata.json)
    echo -e "${INFO} Found package_name in metadata.json: $package_name"
    
    # Check if package is NOT installed before setup
    if adb shell pm list packages | grep -q "^package:$package_name$"; then
        echo -e "${ERROR} Package $package_name is already installed before start_runtime.sh"
        echo -e "${ERROR} This test expects the package to be uninstalled initially"
        exit 1
    else
        echo -e "${SUCCESS} Package $package_name is not installed (as expected before setup)"
    fi

    echo -e "${INFO} Running setup..."
    { ./start_runtime.sh; } || { echo -e "${ERROR} start_runtime.sh failed"; exit 1; }

    # Verify the specific package is installed after setup
    if adb shell pm list packages | grep -q "^package:$package_name$"; then
        echo -e "${SUCCESS} Package $package_name is installed after start_runtime.sh"
    else
        echo -e "${ERROR} Package $package_name is not installed after start_runtime.sh"
        echo -e "${ERROR} This indicates start_runtime.sh failed to install the expected package"
        echo -e "${INFO} Cleaning up..."
        ./cleanup.sh
        exit 1
    fi

    # Wait for app-specific containers to be ready (after start_runtime.sh starts them)
    check_app_containers_ready

    echo -e "${INFO} Generating flags..."
    cd "$ROOT_DIR"
    { "$PYTHON_CMD" -m utils.uuid_flags_utils "$DIR"; } || { echo -e "${ERROR} Flag generation failed"; exit 1; }
    cd "$DIR"

    echo -e "${INFO} Injecting flags..."
    { ../../inject_flags.sh; } || { echo -e "${ERROR} inject_flags.sh failed"; exit 1; }

    run_prepare_victim_if_applicable || exit 1

    verify_shared_net_connectivity
    adb logcat -c

    if [ -n "$vuln_scenario" ]; then
        echo -e "${INFO} Creating vulnerable scenario $vuln_scenario..."
        cd "vuln_scenarios/vuln_scenario_$vuln_scenario"
        chmod +x vuln.sh
        ./vuln.sh
        cd -
    fi

    echo -e "${INFO} Running checks..."
    # Set PYTHONPATH for local testing so generic probes can find utils module
    export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"
    # Opt this caller in to the remote_attacker probe block in run_checks.sh.
    # workflows/base.py:_run_checks (the redteam phase runner) does not set
    # this, so its MA-mode phases skip the RA block.
    export RA_CHECKS_ENABLED=1
    if [ "$use_fake_agent_log" = "true" ] && [ -n "$vuln_scenario" ]; then
        "$ROOT_DIR/run_checks.sh" . "vuln_scenarios/vuln_scenario_$vuln_scenario/fake_agent_log.log"
    else
        "$ROOT_DIR/run_checks.sh" . "$ROOT_DIR/dummy_log.log"
    fi

    if [ -n "$vuln_scenario" ]; then
        # Compare with expected scores (malicious_app probes)
        score1="vuln_scenarios/vuln_scenario_$vuln_scenario/expected_scores.json"
        score2="scores.json"

        if diff <(jq -S . "$score1") <(jq -S . "$score2") >/dev/null; then
            echo -e "${SUCCESS} Scores match"
        else
            echo -e "${ERROR} Scores do not match"
            cat scores.json
            echo -e "${INFO} Cleaning up..."
            ./cleanup.sh
            uninstall_package "$package_name"
            exit 1
        fi

        # Compare remote_attacker scores when both file and expectation exist.
        # The expected fixture is a stable subset of the actual score file:
        # score-affecting probe keys must match exactly, while dynamic
        # diagnostic details may be present only in the actual output.
        ra_expected="vuln_scenarios/vuln_scenario_$vuln_scenario/expected_scores_remote_attacker.json"
        ra_actual="scores_remote_attacker.json"
        if [ -f "$ra_expected" ] && [ -f "$ra_actual" ]; then
            if compare_expected_score_subset "$ra_expected" "$ra_actual"; then
                echo -e "${SUCCESS} remote_attacker scores match"
            else
                echo -e "${ERROR} remote_attacker scores do not match"
                cat "$ra_actual"
                echo -e "${INFO} Cleaning up..."
                ./cleanup.sh
                uninstall_package "$package_name"
                exit 1
            fi
        elif [ -f "$ra_expected" ] && [ ! -f "$ra_actual" ]; then
            echo -e "${ERROR} expected_scores_remote_attacker.json present but scores_remote_attacker.json was not produced"
            echo -e "${INFO} Cleaning up..."
            ./cleanup.sh
            uninstall_package "$package_name"
            exit 1
        fi
    else
        # Check that all scores are 1
        if ! jq -e '[.. | select(type == "number")] | all(. == 1)' scores.json > /dev/null; then
            echo -e "${ERROR} scores.json does not contain all 1s."
            cat scores.json
            echo -e "${INFO} Cleaning up..."
            ./cleanup.sh
            uninstall_package "$package_name"
            exit 1
        fi
        echo -e "${SUCCESS} All scores are 1."

        # Check that all generic scores are 1
        if ! jq -e '[.. | select(type == "number")] | all(. == 1)' generic_scores.json > /dev/null; then
            echo -e "${ERROR} generic_scores.json does not contain all 1s."
            cat generic_scores.json
            echo -e "${INFO} Cleaning up..."
            ./cleanup.sh
            uninstall_package "$package_name"
            exit 1
        fi
        echo -e "${SUCCESS} All generic scores are 1."

        # If the app ships remote_attacker probes, clean-build must also score
        # all 1s. We check only the top-level .scores object (the four CIA
        # dimensions); probe detail blocks are diagnostic and may legitimately
        # contain numeric counts (e.g. extracted_refresh_token_count) that are
        # 0 in a secure state.
        if [ -f scores_remote_attacker.json ]; then
            if ! jq -e '.scores | to_entries | all(.value == 1)' scores_remote_attacker.json > /dev/null; then
                echo -e "${ERROR} scores_remote_attacker.json top-level scores are not all 1s."
                cat scores_remote_attacker.json
                echo -e "${INFO} Cleaning up..."
                ./cleanup.sh
                uninstall_package "$package_name"
                exit 1
            fi
            echo -e "${SUCCESS} All remote_attacker scores are 1."
        fi
    fi

    echo -e "${INFO} Cleaning up..."
    ./cleanup.sh
    uninstall_package "$package_name"
    cd -
}

# Function to run tests for a specific mode
run_tests_for_mode() {
    local setup_mode="$1"
    local dir="$2"
    
    print_header "$CYAN" "TESTING WITH SETUP MODE: $setup_mode"
    
    cd "$ROOT_DIR/$dir"
    
    # Reset the app submodule to the commit declared by this app's metadata.
    # The previous argument here was the app directory, which was then treated
    # as a commit and made `git checkout apps/<app>` fail under normal probe CI.
    checkout_commit
    
    # Check if test_X.py exists to determine test strategy and required scripts
    if [ -f "test_access_control.py" ] || [ -f "test_availability.py" ] || [ -f "test_confidentiality.py" ] || [ -f "test_integrity.py" ]; then
        echo -e "${INFO} test_X.py probe found - running full vulnerability scenario tests"
        HAS_PROBES=true
        required_files=("start_runtime.sh" "cleanup.sh" "test_access_control.py" "test_availability.py" "test_confidentiality.py" "test_integrity.py" "secrets.json")
    else
        echo -e "${INFO} test_X.py probe not found - running simplified APK installation test"
        HAS_PROBES=false
        required_files=("start_runtime.sh" "cleanup.sh")
    fi
    
    echo -e "${INFO} Checking for required scripts..."
    for script in "${required_files[@]}"; do
        if [[ ! -f "$script" ]]; then
            echo -e "${ERROR} Required script '$script' not found."
            exit 1
        fi
    done
    
    # Run appropriate setup script based on mode
    if [ "$setup_mode" = "apk_skip" ]; then
        echo -e "${INFO} apk_skip mode - checking for existing APKs..."
        app_name=$(basename "$dir")
        APK_DIR="$ROOT_DIR/$dir/apk"
        if [ "$OBFUSCATE" = true ]; then
            APK_DIR="$APK_DIR/obfuscated"
        fi

        # Check if APKs exist locally
        APK_COUNT=$(find "$APK_DIR" -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)
        if [ "$APK_COUNT" -eq 0 ]; then
            echo -e "${INFO} No local APKs found, attempting download from download_link..."
            cd "$ROOT_DIR"
            if "$PYTHON_CMD" download_apk.py "${OBFUSCATE_DOWNLOAD_FLAG[@]}" "$app_name"; then
                echo -e "${SUCCESS} Downloaded APKs successfully"
            else
                echo -e "${ERROR} No local APKs and download failed."
                echo -e "${ERROR} To fix: build APK and publish:"
                echo -e "${ERROR}   ./build_apk.sh $app_name ${OBFUSCATE_BUILD_FLAG[*]}"
                echo -e "${ERROR}   ./publish_apk_bundle.sh apps/$app_name"
                echo -e "${ERROR} Or remove --skip-apk to build from source."
                exit 1
            fi
            cd "$ROOT_DIR/$dir"
        else
            echo -e "${SUCCESS} Found $APK_COUNT existing APK(s) in $APK_DIR"
        fi
    elif [ "$setup_mode" = "apklink" ]; then
        echo -e "${INFO} Setting up app from APK link."
        app_name=$(basename "$dir")
        cd "$ROOT_DIR"
        { "$PYTHON_CMD" download_apk.py "${OBFUSCATE_DOWNLOAD_FLAG[@]}" "$app_name"; } || { echo -e "${ERROR} download_apk.py failed"; exit 1; }
        cd "$ROOT_DIR/$dir"
    else
        echo -e "${INFO} Setting up app from source using build_apk.sh..."
        app_name=$(basename "$dir")
        cd "$ROOT_DIR"
        { ./build_apk.sh "$app_name" "${OBFUSCATE_BUILD_FLAG[@]}"; } || { echo -e "${ERROR} build_apk.sh failed"; exit 1; }
        cd "$ROOT_DIR/$dir"
    fi
    
    # Validate APK structure
    echo -e "${INFO} Validating APK structure..."
    APK_DIR="$ROOT_DIR/$dir/apk"
    if [ "$OBFUSCATE" = true ]; then
        APK_DIR="$APK_DIR/obfuscated"
    fi
    if [ ! -d "$APK_DIR" ]; then
        echo -e "${ERROR} APK directory not found at $APK_DIR"
        echo -e "${ERROR} APKs must be placed in $APK_DIR/"
        exit 1
    fi

    APK_COUNT=$(find "$APK_DIR" -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)
    if [ "$APK_COUNT" -eq 0 ]; then
        echo -e "${ERROR} No APK found in $APK_DIR/"
        echo -e "${ERROR} build_apk.sh or download_apk.py must place APKs in ${dir}/apk/"
        exit 1
    fi

    echo -e "${SUCCESS} APK structure validated - found $APK_COUNT APK(s) in $APK_DIR/"

    cd "$ROOT_DIR"
    
    if [ "$HAS_PROBES" = true ]; then
        # Create dummy file for test confidentiality
        cat > "$ROOT_DIR/dummy_log.log" <<'EOF'
# Dummy log file for testing purposes
# This file contains no actual secrets or sensitive information
timestamp=2024-01-01T00:00:00Z
event=test_event
message=dummy test message
status=ok
EOF

        # Run the three test scenarios
        run_test_check "TEST CHECKS BEFORE VULNERABLE SCENARIOS" "" "false"
        run_test_check "TEST CHECKS AFTER NON-DOS VULNERABLE SCENARIO" "0" "true"
        
        # DoS testing is OPTIONAL - only run if app has server/container components
        # Check if app_server field is not an empty string
        cd "$ROOT_DIR/$DIR"
        if [ -f "metadata.json" ]; then
            app_server=$(jq -r '.app_server // empty' metadata.json)
            if [ -n "$app_server" ]; then
                echo -e "${INFO} App has server components ($app_server) - running DoS testing..."
                run_test_check "TEST CHECKS AFTER DOS VULNERABLE SCENARIO" "1" "false"
                DOS_TESTED=true
            else
                echo -e "${INFO} App has no server components (app_server is empty) - skipping DoS testing (not applicable)"
                DOS_TESTED=false
            fi
        else
            echo -e "${INFO} No metadata.json found - skipping DoS testing (not applicable)"
            DOS_TESTED=false
        fi
        cd "$ROOT_DIR"
    else
        # Run simplified test
        print_header "$CYAN" "RUNNING SIMPLIFIED APK INSTALLATION TEST"
        
        cd "$ROOT_DIR"
        cd "$dir"
        
        echo -e "${INFO} Simple APK build and install test - no vulnerability scenarios"
        
        # Get package_name from metadata.json (required field) and verify before setup
        package_name=$(jq -r '.package_name' metadata.json)
        echo -e "${INFO} Found package_name in metadata.json: $package_name"
        
        # Check if package is NOT installed before setup
        if adb shell pm list packages | grep -q "^package:$package_name$"; then
            echo -e "${ERROR} Package $package_name is already installed before start_runtime.sh"
            echo -e "${ERROR} This test expects the package to be uninstalled initially"
            exit 1
        else
            echo -e "${SUCCESS} Package $package_name is not installed (as expected before setup)"
        fi
        
        echo -e "${INFO} Running setup..."
        { ./start_runtime.sh; } || { echo -e "${ERROR} start_runtime.sh failed"; exit 1; }

         # Verify the specific package is installed after setup
        if adb shell pm list packages | grep -q "^package:$package_name$"; then
            echo -e "${SUCCESS} Package $package_name is installed after start_runtime.sh"
        else
            echo -e "${ERROR} Package $package_name is not installed after start_runtime.sh"
            echo -e "${ERROR} This indicates start_runtime.sh failed to install the expected package"
            echo -e "${INFO} Cleaning up..."
            ./cleanup.sh
            exit 1
        fi
        
        # Wait for app-specific containers to be ready (after start_runtime.sh starts them)
        check_app_containers_ready

        echo -e "${INFO} Generating flags..."
        cd "$ROOT_DIR"
        { "$PYTHON_CMD" -m utils.uuid_flags_utils "$dir"; } || { echo -e "${ERROR} Flag generation failed"; exit 1; }
        cd "$dir"

        echo -e "${INFO} Injecting flags..."
        { ../../inject_flags.sh; } || { echo -e "${ERROR} inject_flags.sh failed"; exit 1; }

        run_prepare_victim_if_applicable || exit 1

        verify_shared_net_connectivity
        adb logcat -c
        
        echo -e "${INFO} Cleaning up..."
        ./cleanup.sh
        uninstall_package "$package_name"
        cd -
    fi
    
    # Clean up dummy log file if it exists
    if [ -f "$ROOT_DIR/dummy_log.log" ]; then
        rm "$ROOT_DIR/dummy_log.log"
        echo -e "${INFO} Cleaned up dummy log file"
    fi
    
    print_header "$GREEN" "SETUP MODE $setup_mode COMPLETED SUCCESSFULLY"
}

# Enforce the structural contract between a synth vuln's attacker_model and
# the exploit files it ships. Keep in lockstep with zero_day_task_common.sh
# so the two runtimes accept/reject the same shapes.
validate_vuln_exploit_format() {
    local vuln_abs_dir="$1"
    local attacker_model="$2"
    local exploit_script="$vuln_abs_dir/exploit_files/exploit.sh"
    local exploit_apk_dir="$vuln_abs_dir/exploit_files/exploit_apk"

    if [ -d "$vuln_abs_dir/exploit_files/attacker_app" ]; then
        echo -e "${ERROR} Legacy exploit APK directory is not supported: rename exploit_files/attacker_app to exploit_files/exploit_apk"
        return 1
    fi

    case "$attacker_model" in
        malicious_app)
            if [ -f "$exploit_script" ]; then
                echo -e "${ERROR} attacker_model=malicious_app must not ship exploit_files/exploit.sh (use exploit_files/exploit_apk/)"
                return 1
            fi
            if [ ! -d "$exploit_apk_dir" ]; then
                echo -e "${ERROR} attacker_model=malicious_app requires exploit APK directory: $exploit_apk_dir"
                return 1
            fi
            if ! find "$exploit_apk_dir" -name 'AndroidManifest.xml' -type f -print -quit | grep -q .; then
                echo -e "${ERROR} Exploit APK directory missing AndroidManifest.xml: $exploit_apk_dir"
                return 1
            fi
            if ! find "$exploit_apk_dir" -name '*.java' -type f -print -quit | grep -q .; then
                echo -e "${ERROR} Exploit APK directory must contain at least one .java source file: $exploit_apk_dir"
                return 1
            fi
            ;;
        remote_attacker)
            if [ -d "$exploit_apk_dir" ]; then
                echo -e "${ERROR} attacker_model=remote_attacker must not ship exploit_files/exploit_apk/ (use exploit_files/exploit.sh)"
                return 1
            fi
            if [ ! -f "$exploit_script" ]; then
                echo -e "${ERROR} attacker_model=remote_attacker requires exploit script: $exploit_script"
                return 1
            fi
            ;;
        *)
            echo -e "${ERROR} validate_vuln_exploit_format: unknown attacker_model '$attacker_model'"
            return 1
            ;;
    esac

    return 0
}

# Test a synthetic vulnerability task - both clean and vulnerable builds.
run_vuln_test() {
    local vuln_dir="$1"
    local app_dir="$2"

    print_header "$CYAN" "TESTING SYNTHETIC VULNERABILITY: $vuln_dir"

    # Extract vuln_id from vuln_dir (e.g., "synthetic_vulnerabilities/vuln_0" -> "vuln_0")
    local vuln_id
    vuln_id=$(basename "$vuln_dir")

    # Validate synthetic vulnerability structure
    echo -e "${INFO} Validating synthetic vulnerability structure..."

    local vuln_abs_dir="$ROOT_DIR/$app_dir/$vuln_dir"
    local patch_file="$vuln_abs_dir/vulnerability.patch"
    local exploit_script="$vuln_abs_dir/exploit_files/exploit.sh"
    local exploit_apk_dir="$vuln_abs_dir/exploit_files/exploit_apk"
    local verify_script="$vuln_abs_dir/verify_files/verify_exploit.sh"
    local metadata_file="$vuln_abs_dir/metadata.json"
    if [ ! -f "$patch_file" ]; then
        echo -e "${ERROR} Patch file not found: $patch_file"
        exit 1
    fi

    if [ ! -f "$verify_script" ]; then
        echo -e "${ERROR} Verification script not found: $verify_script"
        exit 1
    fi

    if [ ! -f "$metadata_file" ]; then
        echo -e "${ERROR} metadata.json not found: $metadata_file"
        exit 1
    fi
    if ! load_vuln_test_settings "$vuln_dir" "$app_dir"; then
        exit 1
    fi

    if ! validate_vuln_exploit_format "$vuln_abs_dir" "$VULN_ATTACKER_MODEL"; then
        exit 1
    fi

    echo -e "${INFO} Validating metadata.json schema..."
    if ! (cd "$ROOT_DIR" && python3 -m pytest --no-header -q         tests/test_synthetic_vuln_metadata.py::test_synthetic_vuln_metadata         --dirs "$(dirname "$metadata_file")"); then
        echo -e "${ERROR} metadata.json schema validation failed for $metadata_file"
        exit 1
    fi

    echo -e "${SUCCESS} Synthetic vulnerability structure validated"

    local app_name
    app_name=$(basename "$app_dir")
    local package_name="$VULN_PACKAGE_NAME"
    echo -e "${INFO} Testing app: $app_name"
    echo -e "${INFO} Testing package: $package_name"
    if [ -n "$VULN_TASK_ID" ] && [ "$VULN_TASK_ID" != "null" ]; then
        echo -e "${INFO} Task ID: $VULN_TASK_ID"
    fi
    if [ -n "$VULN_BASELINE_COMMIT" ] && [ "$VULN_BASELINE_COMMIT" != "null" ]; then
        echo -e "${INFO} Baseline commit: $VULN_BASELINE_COMMIT"
    fi
    if [ ${#VULN_BUILD_ENV_ARGS[@]} -gt 0 ]; then
        echo -e "${INFO} Applying task build env: ${VULN_BUILD_ENV_ARGS[*]}"
    fi

    local APK_DIR="$ROOT_DIR/$app_dir/apk"
    if [ "$OBFUSCATE" = true ]; then
        APK_DIR="$APK_DIR/obfuscated"
    fi
    local VULN_APK_DIR="$APK_DIR/$vuln_id"
    local CLEAN_APK_DIR="$APK_DIR"
    local skip_build=false

    if [ "$SKIP_APK" = true ]; then
        echo -e "${INFO} --skip-apk: checking for existing APKs..."

        local base_apk_count
        base_apk_count=$(find "$CLEAN_APK_DIR" -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)
        local vuln_apk_count
        vuln_apk_count=$(find "$VULN_APK_DIR" -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)

        if [ "$base_apk_count" -eq 0 ] || [ "$vuln_apk_count" -eq 0 ]; then
            echo -e "${INFO} Missing APKs (base: $base_apk_count, vuln: $vuln_apk_count), attempting download..."
            cd "$ROOT_DIR"
            if "$PYTHON_CMD" download_apk.py "${OBFUSCATE_DOWNLOAD_FLAG[@]}" "$app_name" 2>/dev/null; then
                echo -e "${SUCCESS} Downloaded APKs"
            fi
            cd "$ROOT_DIR/$app_dir"

            base_apk_count=$(find "$CLEAN_APK_DIR" -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)
            vuln_apk_count=$(find "$VULN_APK_DIR" -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)
        fi

        if [ "$base_apk_count" -gt 0 ] && [ "$vuln_apk_count" -gt 0 ]; then
            echo -e "${SUCCESS} Found existing APKs: base=$base_apk_count, vuln=$vuln_apk_count"
            skip_build=true
        else
            echo -e "${ERROR} --skip-apk requires both base APK and vulnerable APK to exist"
            echo -e "${ERROR} Base APK: $CLEAN_APK_DIR/*.apk ($base_apk_count found)"
            echo -e "${ERROR} Vuln APK: $VULN_APK_DIR/*.apk ($vuln_apk_count found)"
            echo -e "${ERROR} To fix: build APKs and publish:"
            echo -e "${ERROR}   $(printf '%q ' "${VULN_BUILD_ENV_ARGS[@]}")./build_apk.sh $app_name ${OBFUSCATE_BUILD_FLAG[*]}"
            echo -e "${ERROR}   $(printf '%q ' "${VULN_BUILD_ENV_ARGS[@]}")./build_apk.sh $app_name --vuln $vuln_dir ${OBFUSCATE_BUILD_FLAG[*]}"
            echo -e "${ERROR}   ./publish_apk_bundle.sh apps/$app_name"
            exit 1
        fi
    fi

    if [ "$skip_build" = false ]; then
        print_header "$CYAN" "BUILD PHASE: Building all APKs (emulator not running)"

        cd "$ROOT_DIR"

        echo -e "${INFO} Building clean APK using build_apk.sh..."
        if ! run_build_apk_with_vuln_env "$app_name"; then
            echo -e "${ERROR} Failed to build clean APK"
            exit 1
        fi

        echo -e "${INFO} Building vulnerable APK using build_apk.sh --vuln $vuln_dir..."
        if ! run_build_apk_with_vuln_env "$app_name" --vuln "$vuln_dir"; then
            echo -e "${ERROR} Failed to build vulnerable APK"
            exit 1
        fi

        print_header "$GREEN" "BUILD PHASE COMPLETE: Both APKs built successfully"
    else
        echo -e "${INFO} Using existing APKs (--skip-apk)"
        (cd "$ROOT_DIR/$app_dir" && checkout_commit "${VULN_BASELINE_COMMIT:-}")
    fi

    cd "$ROOT_DIR"
    start_emulator_and_adb
    if ! task_validation_resolve_android_serial; then
        exit 1
    fi

    local task_abs_path
    task_abs_path="$(cd "$ROOT_DIR/$app_dir/$vuln_dir" && pwd)"
    local agent_output_abs_path="$task_abs_path/agent_output"
    local fix_patch_path=""
    if [ -f "$task_abs_path/fix.patch" ]; then
        fix_patch_path="$task_abs_path/fix.patch"
    fi

    if ! task_validation_set_context \
        "$ROOT_DIR" \
        "$ROOT_DIR/$app_dir" \
        "$task_abs_path" \
        "$agent_output_abs_path" \
        "" \
        "" \
        "$package_name" \
        "${VULN_TASK_ID:-$vuln_id}" \
        "${VULN_BASELINE_COMMIT:-}" \
        "${VULN_ATTACKER_MODEL:-}" \
        "$fix_patch_path" \
        "" \
        "flat" \
        "true"; then
        echo -e "${ERROR} Failed to initialize task validation context"
        exit 1
    fi

    print_header "$CYAN" "PHASE 1: Testing Clean Build (Baseline)"
    if ! task_validation_run_phase "Clean build" "secure" "" "false"; then
        echo -e "${ERROR} Phase 1 failed: Clean build verification failed"
        task_validation_cleanup_runtime
        exit 1
    fi

    echo -e "${INFO} Cleaning up Phase 1..."
    task_validation_cleanup_runtime
    print_header "$GREEN" "PHASE 1 PASSED: Clean build is NOT vulnerable"

    print_header "$CYAN" "PHASE 2: Testing Vulnerable Build (With Patch)"
    local vuln_apk="$(mcb_apk_subdir)/${vuln_id}/${app_name}.apk"
    if [ ! -f "$vuln_apk" ]; then
        echo -e "${ERROR} Vulnerable APK not found: $vuln_apk"
        exit 1
    fi

    SYNTH_RUNTIME_PATCH_FILE="$patch_file"
    if ! task_validation_run_phase "Vulnerable build" "vulnerable" "$vuln_apk" "true" "synthetic_phase_apply_vulnerability_patch"; then
        echo -e "${ERROR} Phase 2 failed: Vulnerable build verification failed"
        echo -e "${INFO} Restoring codebase after vulnerable phase..."
        (cd "$ROOT_DIR/$app_dir/codebase" && git reset --hard HEAD && git clean -fdx             && git submodule foreach --recursive git reset --hard HEAD 2>/dev/null || true             && git submodule foreach --recursive git clean -fdx 2>/dev/null || true) 2>/dev/null || true
        task_validation_cleanup_runtime
        exit 1
    fi

    echo -e "${INFO} Restoring codebase after vulnerable phase..."
    (cd "$ROOT_DIR/$app_dir/codebase" && git reset --hard HEAD && git clean -fdx         && git submodule foreach --recursive git reset --hard HEAD 2>/dev/null || true         && git submodule foreach --recursive git clean -fdx 2>/dev/null || true)

    echo -e "${INFO} Cleaning up Phase 2..."
    task_validation_cleanup_runtime

    print_header "$GREEN" "PHASE 2 PASSED: Vulnerable build IS vulnerable"
    print_header "$GREEN" "SYNTHETIC VULNERABILITY TEST COMPLETE: $vuln_dir"
}

# Create Docker networks before any app compose runs. agent_net is internal
# (kernel-level egress firewall); pilot apps declare it as external.
print_header "$CYAN" "CREATING DOCKER NETWORKS"
echo -e "${INFO} Creating shared_net network..."
docker network create shared_net || echo -e "${INFO} shared_net network already exists"
echo -e "${INFO} Creating agent_net network (internal)..."
docker network create --internal agent_net || echo -e "${INFO} agent_net network already exists"

# Start SSRF Listener
print_header "$CYAN" "STARTING SSRF LISTENER"
start_ssrf_listener || echo -e "${WARNING} SSRF listener not started - SSRF detection may not work"

# Function to start emulator and configure ADB
start_emulator_and_adb() {
    if [ -f "start_emulator.sh" ]; then
        print_header "$CYAN" "STARTING EMULATOR"
        bash ./stop_emulator.sh >/dev/null  # Stop any emulator running in the background before starting local CI.
        # Delegates to emulator.py start — handles boot wait and ADB setup
        bash ./start_emulator.sh "$sdk" || { echo -e "${ERROR} Failed to start emulator"; exit 1; }

        # Ensure emulator is stopped on any exit (success or failure)
        trap 'echo -e "${INFO} Stopping emulator due to script exit..."; cd "$ROOT_DIR"; bash ./stop_emulator.sh' EXIT
    else
        echo -e "${WARNING} start_emulator.sh not found, assuming emulator is already running"
    fi

    # ADB -a binding is handled by EmulatorManager (via emulator.py start)

    # Inject system CA so apps trust local HTTPS backends
    echo -e "${INFO} Injecting system CA certificate..."
    if [ -f "${ROOT_DIR}/utils/inject_system_ca.sh" ]; then
        bash "${ROOT_DIR}/utils/inject_system_ca.sh" || echo -e "${WARNING} CA injection failed"
    else
        echo -e "${WARNING} inject_system_ca.sh not found, skipping CA injection"
    fi
}

# Expand --test-all-synthetic-vulns into the list of vuln directories
if [ "$TEST_ALL_SYNTHETIC_VULNS" = true ]; then
    SYNTH_VULN_DIRS=()
    for d in "$DIR"/synthetic_vulnerabilities/vuln_*/; do
        [ -d "$d" ] && SYNTH_VULN_DIRS+=("synthetic_vulnerabilities/$(basename "$d")")
    done
    if [ ${#SYNTH_VULN_DIRS[@]} -eq 0 ]; then
        echo -e "${ERROR} No synthetic vulnerability directories found in $DIR/synthetic_vulnerabilities/"
        exit 1
    fi
    echo -e "${INFO} Found ${#SYNTH_VULN_DIRS[@]} synthetic vulnerability(ies): ${SYNTH_VULN_DIRS[*]}"
fi

# For synthetic vuln tests, delay emulator start until after APKs are built.
# This avoids the emulator competing for CPU during long native builds.
if [ -z "$TEST_SYNTHETIC_VULN" ] && [ -z "$TEST_ZERO_DAY_VULN" ] && [ "$TEST_ALL_SYNTHETIC_VULNS" = false ]; then
    start_emulator_and_adb
fi

# Check if we're running synthetic vulnerability tests
if [ "$TEST_ALL_SYNTHETIC_VULNS" = true ]; then
    print_header "$CYAN" "RUNNING ALL SYNTHETIC VULNERABILITY TESTS"
    for VULN_DIR in "${SYNTH_VULN_DIRS[@]}"; do
        print_header "$CYAN" "TESTING SYNTHETIC VULNERABILITY: $VULN_DIR"
        run_vuln_test "$VULN_DIR" "$DIR"
    done
    SKIP_NORMAL_TESTS=true
elif [ -n "$TEST_SYNTHETIC_VULN" ]; then
    print_header "$CYAN" "RUNNING SYNTHETIC VULNERABILITY TEST MODE"

    # Validate that the vulnerability directory exists
    if [ ! -d "$DIR/$TEST_SYNTHETIC_VULN" ]; then
        echo -e "${ERROR} Synthetic vulnerability directory not found: $DIR/$TEST_SYNTHETIC_VULN"
        exit 1
    fi

    # Run synthetic vulnerability test
    run_vuln_test "$TEST_SYNTHETIC_VULN" "$DIR"

    # Skip normal test flow
    SKIP_NORMAL_TESTS=true
elif [ -n "$TEST_ZERO_DAY_VULN" ]; then
    print_header "$CYAN" "RUNNING ZERO-DAY TASK VALIDATION"

    if [ ! -d "$DIR/$TEST_ZERO_DAY_VULN" ]; then
        echo -e "${ERROR} Zero-day task directory not found: $DIR/$TEST_ZERO_DAY_VULN"
        exit 1
    fi

    run_zero_day_task "$TEST_ZERO_DAY_VULN" "$DIR"

    # Skip normal test flow
    SKIP_NORMAL_TESTS=true
else
    SKIP_NORMAL_TESTS=false
    SETUP_MODES=$(determine_setup_modes "$DIR")
fi

# Run tests for each setup mode (unless we're in synthetic vuln test mode)
if [ "$SKIP_NORMAL_TESTS" = false ]; then
    for SETUP_MODE in $SETUP_MODES; do
        run_tests_for_mode "$SETUP_MODE" "$DIR"
    done
fi

# Calculate total runtime
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
MINUTES=$((DURATION / 60))
SECONDS=$((DURATION % 60))

SETUP_MODE_COUNT=0
if [ "$SKIP_NORMAL_TESTS" = false ]; then
    SETUP_MODE_COUNT=$(echo $SETUP_MODES | wc -w)
fi

# Handle synthetic vulnerability test results
if [ "$TEST_ALL_SYNTHETIC_VULNS" = true ]; then
    print_header "$GREEN" "ALL SYNTHETIC VULNERABILITY TESTS COMPLETED"
    for VULN_DIR in "${SYNTH_VULN_DIRS[@]}"; do
        echo -e "${SUCCESS} ✓ $VULN_DIR passed"
    done
    echo -e "${INFO} Total runtime: ${MINUTES}m ${SECONDS}s"
elif [ -n "$TEST_SYNTHETIC_VULN" ]; then
    print_header "$GREEN" "SYNTHETIC VULNERABILITY TEST COMPLETED"
    echo -e "${SUCCESS} Tested vulnerability: $TEST_SYNTHETIC_VULN"
    echo -e "${SUCCESS} ✓ Clean build verification passed"
    echo -e "${SUCCESS} ✓ Vulnerable build verification passed"
    echo -e "${INFO} Total runtime: ${MINUTES}m ${SECONDS}s"
elif [ -n "$TEST_ZERO_DAY_VULN" ]; then
    print_header "$GREEN" "ZERO-DAY TASK VALIDATION COMPLETED"
    echo -e "${SUCCESS} Tested task: $TEST_ZERO_DAY_VULN"
    echo -e "${SUCCESS} ✓ Secure build is NOT vulnerable"
    echo -e "${SUCCESS} ✓ Vulnerable build IS vulnerable"
    echo -e "${INFO} Total runtime: ${MINUTES}m ${SECONDS}s"
elif [ "$HAS_PROBES" = true ]; then
    print_header "$GREEN" "ALL TESTS PASSED"
    print_header "$GREEN" "FULL CI COMPLETED SUCCESSFULLY"
    echo -e "${SUCCESS} Complete vulnerability testing performed:"
    echo -e "${SUCCESS} ✓ Baseline scenario"  
    echo -e "${SUCCESS} ✓ Vulnerability scenario 0 (non-DoS)"
    if [ "$DOS_TESTED" = true ]; then
        echo -e "${SUCCESS} ✓ Vulnerability scenario 1 (DoS) - server components detected"
    else
        echo -e "${INFO} Vulnerability scenario 1 (DoS) - skipped (no server components)"
    fi
    echo -e "${SUCCESS} ✓ All CIAA (Confidentiality, Integrity, Availability, Access Control) checks"
    if [ "$SETUP_MODE_COUNT" -gt 1 ]; then
        echo -e "${SUCCESS} ✓ Tested with multiple setup modes: $SETUP_MODES"
        echo -e "${INFO} Total runtime: ${MINUTES}m ${SECONDS}s (Setup modes: $SETUP_MODES)"
    else
        echo -e "${INFO} Total runtime: ${MINUTES}m ${SECONDS}s (Setup mode: $SETUP_MODES)"
    fi
else
    print_header "$GREEN" "BASIC TESTS PASSED"
    print_header "$YELLOW" "SIMPLIFIED CI COMPLETED - FULL CI NOT RUN"
    echo ""
    echo -e "${WARNING} ⚠️  IMPORTANT: Only basic APK installation testing was performed"
    echo -e "${WARNING} ⚠️  Full vulnerability scenario testing was NOT run"
    echo ""  
    echo -e "${INFO} To enable full CI testing, this app needs:"
    echo -e "${INFO} • Any test_access_control.py, test_availability.py, test_confidentiality.py, test_integrity.py probe script"
    echo -e "${INFO} • Vulnerability scenario implementations"
    echo -e "${INFO} • Full CIAA security test coverage"
    echo ""
    echo -e "${CYAN} The GitHub CI will also run in simplified mode for this app"
    echo -e "${CYAN} until a test_X.py probe script is added."
    if [ "$SETUP_MODE_COUNT" -gt 1 ]; then
        echo -e "${INFO} Total runtime: ${MINUTES}m ${SECONDS}s (Setup modes: $SETUP_MODES)"
    else
        echo -e "${INFO} Total runtime: ${MINUTES}m ${SECONDS}s (Setup mode: $SETUP_MODES)"
    fi
fi

cd $ROOT_DIR

# Stop SSRF listener
print_header "$CYAN" "STOPPING SSRF LISTENER"
stop_ssrf_listener

# Run linter only for the normal local-CI path. Targeted task validation modes
# should not fail on unrelated changed Python files or local lint PATH issues.
print_header "$CYAN" "RUNNING LINTER"
if [ "$SKIP_NORMAL_TESTS" = true ]; then
    echo -e "${INFO} Skipping linter for targeted task validation mode"
elif [ -f "run_linter.sh" ]; then
    echo -e "${INFO} Running linter..."
    { ./run_linter.sh; } || { echo -e "${ERROR} run_linter.sh failed"; exit 1; }
    echo -e "${SUCCESS} Linter completed successfully"
else
    echo -e "${WARNING} run_linter.sh not found, skipping linter"
fi

# Final Timing and Summary
print_header "$CYAN" "FINAL TIMING AND SUMMARY"
if [ "$TEST_ALL_SYNTHETIC_VULNS" = true ]; then
    print_header "$GREEN" "ALL SYNTHETIC VULNERABILITY TESTS COMPLETED SUCCESSFULLY"
    echo -e "${SUCCESS} Total execution time: ${MINUTES}m ${SECONDS}s"
elif [ -n "$TEST_SYNTHETIC_VULN" ]; then
    print_header "$GREEN" "SYNTHETIC VULNERABILITY TEST COMPLETED SUCCESSFULLY"
    echo -e "${SUCCESS} Total execution time: ${MINUTES}m ${SECONDS}s"
elif [ -n "$TEST_ZERO_DAY_VULN" ]; then
    print_header "$GREEN" "ZERO-DAY TASK VALIDATION COMPLETED SUCCESSFULLY"
    echo -e "${SUCCESS} Total execution time: ${MINUTES}m ${SECONDS}s"
elif [ "$HAS_PROBES" = true ]; then
    print_header "$GREEN" "LOCAL CIA TESTS COMPLETED SUCCESSFULLY"
    echo -e "${SUCCESS} Total execution time: ${MINUTES}m ${SECONDS}s using modes: $SETUP_MODES"
else
    print_header "$YELLOW" "LOCAL BASIC TESTS COMPLETED - ADD test_X.py probe script FOR FULL CI"
    echo -e "${INFO} Total execution time: ${MINUTES}m ${SECONDS}s using modes: $SETUP_MODES"
fi
