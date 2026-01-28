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
source "${ROOT_DIR}/utils/android.sh"
source "${ROOT_DIR}/utils/wait.sh"
set +e

DIR=""

print_header() {
    local color="$1"
    local message="$2"
    echo -e "${color}========== ${message} ==========${RESET}"
}

check_metadata_schema() {
    local metadata_file="$1"
    echo "Checking metadata.json against expected schema..."

    if ! jq empty "$metadata_file" >/dev/null 2>&1; then
        print_header "$ERROR" "[FAIL] Invalid JSON in $metadata_file"
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
            print_header "$ERROR" "[FAIL] Attribute $field is not in the metadata."
            print_header "$ERROR" " --> Attribute ${description} is not in the metadata."
            all_passed=false
        fi
    done

    if [ "$all_passed" = true ]; then
        print_header "$GREEN" "[PASS] Metadata schema validation success."
    else
        print_header "$ERROR" "[FAIL] Metadata schema validation failed."
        exit 1
    fi
}

check_app_containers_ready() {
    # Timeout per container in seconds
    TIMEOUT=${TIMEOUT:-180}
    # Interval between checks in seconds
    INTERVAL=${INTERVAL:-1}

    # Get app-specific containers from metadata.json
    containers=""
    if [ -f "metadata.json" ]; then
        # Check for explicit container_names field
        container_names=$(jq -r '.container_names[]? // empty' metadata.json 2>/dev/null)
        if [ -n "$container_names" ]; then
            containers="$container_names"
            echo "Found explicit container_names in metadata.json: $containers"
        fi
    fi

    if [ -z "$containers" ]; then
        echo "No app-specific containers found in metadata.json - skipping container readiness check"
        return 0
    fi

    echo "Checking readiness for app-specific containers: $containers"

    for container in $containers; do
        echo "Checking readiness for $container..."

        # Check if container has a health check
        has_health=$(docker inspect --format '{{if .Config.Healthcheck}}true{{else}}false{{end}}' "$container")
        if [ "$has_health" = "true" ]; then
            echo "Container has a health check. Waiting to become healthy..."
            elapsed=0
            success=0
            while [ $elapsed -lt $TIMEOUT ]; do
                status=$(docker inspect --format '{{.State.Health.Status}}' "$container" 2>/dev/null)
                if [ "$status" == "healthy" ]; then
                    success=1
                    break
                fi
                sleep "$INTERVAL"
                elapsed=$((elapsed + INTERVAL))
            done
            if [ $success -eq 1 ]; then
                echo "$container is healthy."
                continue
            else
                echo "Timeout: $container did not become healthy within $TIMEOUT seconds." >&2
                exit 1
            fi
        else
            # Get exposed TCP ports
            ports=$(docker inspect --format '{{range $p, $conf := .NetworkSettings.Ports}}{{range $conf}}{{.HostPort}} {{end}}{{end}}' "$container")
            if [ -z "$ports" ]; then
                echo "No exposed ports for $container. Skipping readiness check." >&2
                continue
            fi

            elapsed=0
            all_success=0
            while [ $elapsed -lt $TIMEOUT ]; do
                success=1
                for port_spec in $ports; do
                    port=$(echo "$port_spec" | cut -d'/' -f1)
                    proto=$(echo "$port_spec" | cut -d'/' -f2)
                    if [ "$proto" != "tcp" ]; then
                        continue  # Skip non-TCP ports
                    fi

                    # Perform TCP check
                    if ! nc -z -w 1 localhost "$port" &>/dev/null; then
                        success=0
                        break
                    fi
                done

                if [ $success -eq 1 ]; then
                    all_success=1
                    break
                fi

                sleep "$INTERVAL"
                elapsed=$((elapsed + INTERVAL))
            done

            if [ $all_success -eq 1 ]; then
                echo "$container is ready via port check on all ports."
            else
                echo "Timeout: $container not ready after $TIMEOUT seconds." >&2
                exit 1
            fi
        fi
    done

    echo "App-specific containers are ready!"
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

    local source_script="$dir/setup_app_source.sh"
    local has_download_link=false

    # Check if download_link exists in metadata.json
    if [ -f "$dir/metadata.json" ]; then
        download_link=$(jq -r '.download_link // empty' "$dir/metadata.json")
        if [ -n "$download_link" ]; then
            has_download_link=true
        fi
    fi

    if [ ! -f "$source_script" ] && [ "$has_download_link" = false ]; then
        # fail if neither option exists
        echo -e "${ERROR} No setup options found in $dir" >&2
        echo -e "${ERROR} Expected: setup_app_source.sh or download_link in metadata.json" >&2
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
        if [ -f "$dir/setup_app_source.sh" ]; then
            modes="$modes source"
            echo -e "${INFO} Found setup_app_source.sh (build mode)" >&2
        fi
        # Check if download_link exists in metadata.json
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

checkout_commit() {
    echo "Current directory: $(pwd)"
    if [[ -f "metadata.json" ]]; then
        commit=$(jq -r '.["commit_version"]' "metadata.json")
        
        if [[ -n "$commit" ]]; then
            echo "Found commit: $commit"

            git submodule update --init codebase
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

# Run exploit and verification for synthetic vulnerability
run_exploit_verification() {
    local vuln_dir="$1"
    local expect_vulnerable="$2"  # "true" or "false"

    echo -e "${INFO} Running exploit from: $vuln_dir"

    # Check required files
    local exploit_files_dir="$vuln_dir/exploit_files"
    local exploit_script="$exploit_files_dir/exploit.sh"
    local verify_script="$vuln_dir/verify_files/verify_exploit.sh"

    if [ ! -f "$exploit_script" ]; then
        echo -e "${ERROR} Exploit script not found: $exploit_script"
        return 1
    fi
    
    if [ ! -f "$verify_script" ]; then
        echo -e "${ERROR} Verification script not found: $verify_script"
        return 1
    fi

    # Run exploit in container
    echo -e "${INFO} Executing exploit in container..."
    local container_name="mobilecybench-exploit-$$"
    local exploit_image="${EXPLOIT_IMAGE:-cybench/mobilecybench:latest}"
    local exploit_files_abs_path
    exploit_files_abs_path="$(cd "$exploit_files_dir" && pwd)"

    # Calculate mobilecybench utils directory path (needed for utils.ui_utils imports)
    # Use ROOT_DIR which is set at the top of run_ci_local.sh (mobilecybench root)
    local utils_dir="$ROOT_DIR/utils"

    # Start container with exploit_files and utils mounted
    echo -e "${INFO} Starting exploit container: $container_name"
    docker run -d \
        --name "$container_name" \
        --network=shared_net \
        --add-host=host.docker.internal:host-gateway \
        -e ADB_SERVER_SOCKET=tcp:host.docker.internal:5037 \
        -e PYTHONPATH=/app \
        -v "$exploit_files_abs_path:/app/exploit_files" \
        -v "$utils_dir:/app/utils" \
        "$exploit_image" \
        tail -f /dev/null

    echo -e "${INFO} Verifying container→emulator ADB connection..."
    if ! docker exec "$container_name" adb devices 2>/dev/null | grep -q "device$"; then
        echo -e "${WARNING} Container cannot see the emulator via ADB."
        echo -e "${WARNING} This is OK for network-only exploits, but exploits requiring ADB may fail."
    else
        echo -e "${SUCCESS} Container can access emulator via ADB"
    fi

    # Run the exploit script inside the container
    if docker exec "$container_name" bash /app/exploit_files/exploit.sh; then
        echo -e "${SUCCESS} Exploit executed successfully"
    else
        echo -e "${WARNING} Exploit execution returned non-zero exit code (may be expected)"
    fi

    # Stop and remove the container
    echo -e "${INFO} Cleaning up exploit container..."
    docker rm -f "$container_name" 2>/dev/null || true
    
    # Run verification
    echo -e "${INFO} Running verification..."
    bash "$verify_script"
    local verify_exit_code=$?

    if [ "$verify_exit_code" -eq 0 ]; then
        # verify_exploit.sh returns 0 if vulnerable
        if [ "$expect_vulnerable" = "true" ]; then
            echo -e "${SUCCESS} Verification passed: App is vulnerable (as expected)"
            return 0
        else
            echo -e "${ERROR} Verification failed: App is vulnerable (expected NOT vulnerable)"
            return 1
        fi
    elif [ "$verify_exit_code" -eq 1 ]; then
        # verify_exploit.sh returns 1 if not vulnerable
        if [ "$expect_vulnerable" = "false" ]; then
            echo -e "${SUCCESS} Verification passed: App is NOT vulnerable (as expected)"
            return 0
        else
            echo -e "${ERROR} Verification failed: App is NOT vulnerable (expected vulnerable)"
            return 1
        fi
    else
        # Any other exit code indicates an error in the verification script
        echo -e "${ERROR} Verification script failed with unexpected exit code: $verify_exit_code"
        echo -e "${ERROR} This indicates an error in verify_exploit.sh (e.g., adb/db failure), not a vulnerability status"
        return 1
    fi
}

# Parse command line arguments
SKIP_BUILD=false
SKIP_DOWNLOAD=false
SKIP_APK=false
RUN_UNIT_TESTS=false
TEST_SYNTHETIC_VULN=""

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

    # Mirror CI: for vuln_scenario_0 only, prepare rooted/remounted emulator BEFORE setup
    if [ -n "$vuln_scenario" ] && [ "$vuln_scenario" = "0" ]; then
        echo -e "${INFO} Preparing rooted/remounted emulator (CI parity for vuln_scenario_0)"
        if [ -f "utils/android_emulator_ready.sh" ]; then
            utils/android_emulator_ready.sh --remount || true
        else
            adb get-state 1>/dev/null 2>&1 || adb wait-for-device
            adb root || true
            adb wait-for-device
            adb shell avbctl disable-verification || true
            adb reboot || true
            adb wait-for-device
            adb root || true
            adb remount || true
        fi
        adb logcat -c || true
    fi
    
    # Get package_name from metadata.json (required field) and verify before setup
    package_name=$(jq -r '.package_name' metadata.json)
    echo -e "${INFO} Found package_name in metadata.json: $package_name"
    
    # Check if package is NOT installed before setup
    if adb shell pm list packages | grep -q "^package:$package_name$"; then
        echo -e "${ERROR} Package $package_name is already installed before setup.sh"
        echo -e "${ERROR} This test expects the package to be uninstalled initially"
        exit 1
    else
        echo -e "${SUCCESS} Package $package_name is not installed (as expected before setup)"
    fi

    echo -e "${INFO} Running setup..."
    { ./setup.sh; } || { echo -e "${ERROR} setup.sh failed"; exit 1; }

    # Verify the specific package is installed after setup
    if adb shell pm list packages | grep -q "^package:$package_name$"; then
        echo -e "${SUCCESS} Package $package_name is installed after setup.sh"
    else
        echo -e "${ERROR} Package $package_name is not installed after setup.sh"
        echo -e "${ERROR} This indicates setup.sh failed to install the expected package"
        echo -e "${INFO} Cleaning up..."
        ./cleanup.sh
        exit 1
    fi

    # Wait for app-specific containers to be ready (after setup.sh starts them)
    check_app_containers_ready

    echo -e "${INFO} Generating flags..."
    cd "$ROOT_DIR"
    { python -m utils.uuid_flags_utils "$DIR"; } || { echo -e "${ERROR} Flag generation failed"; exit 1; }
    cd "$DIR"

    echo -e "${INFO} Injecting flags..."
    { ../../inject_flags.sh; } || { echo -e "${ERROR} inject_flags.sh failed"; exit 1; }
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
    if [ "$use_fake_agent_log" = "true" ] && [ -n "$vuln_scenario" ]; then
        "$ROOT_DIR/run_checks.sh" . "vuln_scenarios/vuln_scenario_$vuln_scenario/fake_agent_log.log"
    else
        "$ROOT_DIR/run_checks.sh" . "$ROOT_DIR/dummy_log.log"
    fi

    if [ -n "$vuln_scenario" ]; then
        # Compare with expected scores
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
    
    # Skip this step if you want to persist your apk
    checkout_commit "$dir"
    
    # Check if test_X.py exists to determine test strategy and required scripts
    if [ -f "test_access_control.py" ] || [ -f "test_availability.py" ] || [ -f "test_confidentiality.py" ] || [ -f "test_integrity.py" ]; then
        echo -e "${INFO} test_X.py probe found - running full vulnerability scenario tests"
        local has_probes=true
        required_files=("setup.sh" "cleanup.sh" "test_access_control.py" "test_availability.py" "test_confidentiality.py" "test_integrity.py" "secrets.json")
    else
        echo -e "${INFO} test_X.py probe not found - running simplified APK installation test"
        local has_probes=false
        required_files=("setup.sh" "cleanup.sh")
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

        # Check if APKs exist locally
        APK_COUNT=$(find "$APK_DIR" -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)
        if [ "$APK_COUNT" -eq 0 ]; then
            echo -e "${INFO} No local APKs found, attempting download from download_link..."
            cd "$ROOT_DIR"
            if python setup_app_apklink.py "$app_name"; then
                echo -e "${SUCCESS} Downloaded APKs successfully"
            else
                echo -e "${ERROR} No local APKs and download failed."
                echo -e "${ERROR} To fix: build APK and publish:"
                echo -e "${ERROR}   ./build_apk.sh $app_name"
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
        { python setup_app_apklink.py "$app_name"; } || { echo -e "${ERROR} setup_app_apklink.py failed"; exit 1; }
        cd "$ROOT_DIR/$dir"
    else
        echo -e "${INFO} Setting up app from source using build_apk.sh..."
        app_name=$(basename "$dir")
        cd "$ROOT_DIR"
        { ./build_apk.sh "$app_name"; } || { echo -e "${ERROR} build_apk.sh failed"; exit 1; }
        cd "$ROOT_DIR/$dir"
    fi
    
    # Validate APK structure
    echo -e "${INFO} Validating APK structure..."
    APK_DIR="$ROOT_DIR/$dir/apk"
    if [ ! -d "$APK_DIR" ]; then
        echo -e "${ERROR} APK directory not found at $APK_DIR"
        echo -e "${ERROR} APKs must be placed in ${dir}/apk/"
        exit 1
    fi

    APK_COUNT=$(find "$APK_DIR" -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)
    if [ "$APK_COUNT" -eq 0 ]; then
        echo -e "${ERROR} No APK found in $APK_DIR/"
        echo -e "${ERROR} setup_app_source.sh or setup_app_apklink.py must place APKs in ${dir}/apk/"
        exit 1
    fi

    echo -e "${SUCCESS} APK structure validated - found $APK_COUNT APK(s) in $APK_DIR/"

    cd "$ROOT_DIR"
    
    if [ "$has_probes" = true ]; then
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
            echo -e "${ERROR} Package $package_name is already installed before setup.sh"
            echo -e "${ERROR} This test expects the package to be uninstalled initially"
            exit 1
        else
            echo -e "${SUCCESS} Package $package_name is not installed (as expected before setup)"
        fi
        
        echo -e "${INFO} Running setup..."
        { ./setup.sh; } || { echo -e "${ERROR} setup.sh failed"; exit 1; }

         # Verify the specific package is installed after setup
        if adb shell pm list packages | grep -q "^package:$package_name$"; then
            echo -e "${SUCCESS} Package $package_name is installed after setup.sh"
        else
            echo -e "${ERROR} Package $package_name is not installed after setup.sh"
            echo -e "${ERROR} This indicates setup.sh failed to install the expected package"
            echo -e "${INFO} Cleaning up..."
            ./cleanup.sh
            exit 1
        fi
        
        # Wait for app-specific containers to be ready (after setup.sh starts them)
        check_app_containers_ready

        echo -e "${INFO} Generating flags..."
        cd "$ROOT_DIR"
        { python -m utils.uuid_flags_utils "$dir"; } || { echo -e "${ERROR} Flag generation failed"; exit 1; }
        cd "$dir"

        echo -e "${INFO} Injecting flags..."
        { ../../inject_flags.sh; } || { echo -e "${ERROR} inject_flags.sh failed"; exit 1; }
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

# Test synthetic vulnerability - both clean and vulnerable builds
run_synthetic_vuln_test() {
    local vuln_dir="$1"
    local app_dir="$2"

    print_header "$CYAN" "TESTING SYNTHETIC VULNERABILITY: $vuln_dir"

    # Extract vuln_id from vuln_dir (e.g., "synthetic_vulnerabilities/vuln_0" -> "vuln_0")
    local vuln_id
    vuln_id=$(basename "$vuln_dir")

    # Validate synthetic vulnerability structure
    echo -e "${INFO} Validating synthetic vulnerability structure..."

    local patch_file="$ROOT_DIR/$app_dir/$vuln_dir/vulnerability.patch"
    local exploit_script="$ROOT_DIR/$app_dir/$vuln_dir/exploit_files/exploit.sh"
    local verify_script="$ROOT_DIR/$app_dir/$vuln_dir/verify_files/verify_exploit.sh"
    
    if [ ! -f "$patch_file" ]; then
        echo -e "${ERROR} Patch file not found: $patch_file"
        exit 1
    fi

    if [ ! -f "$exploit_script" ]; then
        echo -e "${ERROR} Exploit script not found: $exploit_script"
        exit 1
    fi

    if [ ! -f "$verify_script" ]; then
        echo -e "${ERROR} Verification script not found: $verify_script"
        exit 1
    fi

    echo -e "${SUCCESS} Synthetic vulnerability structure validated"

    # Get app name and package name from metadata
    local app_name
    app_name=$(basename "$app_dir")
    local package_name
    package_name=$(jq -r '.package_name' "$app_dir/metadata.json")
    echo -e "${INFO} Testing app: $app_name"
    echo -e "${INFO} Testing package: $package_name"

    # Check for existing APKs when --skip-apk is set
    local APK_DIR="$ROOT_DIR/$app_dir/apk"
    local VULN_APK_DIR="$APK_DIR/$vuln_id"
    local skip_build=false

    if [ "$SKIP_APK" = true ]; then
        echo -e "${INFO} --skip-apk: checking for existing APKs..."

        # Check if base APK exists
        local base_apk_count=$(find "$APK_DIR" -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)
        local vuln_apk_count=$(find "$VULN_APK_DIR" -name "*.apk" -type f 2>/dev/null | wc -l)

        if [ "$base_apk_count" -eq 0 ] || [ "$vuln_apk_count" -eq 0 ]; then
            echo -e "${INFO} Missing APKs (base: $base_apk_count, vuln: $vuln_apk_count), attempting download..."
            cd "$ROOT_DIR"
            if python setup_app_apklink.py "$app_name" 2>/dev/null; then
                echo -e "${SUCCESS} Downloaded APKs"
            fi
            cd "$ROOT_DIR/$app_dir"

            # Recheck after download
            base_apk_count=$(find "$APK_DIR" -maxdepth 1 -name "*.apk" -type f 2>/dev/null | wc -l)
            vuln_apk_count=$(find "$VULN_APK_DIR" -name "*.apk" -type f 2>/dev/null | wc -l)
        fi

        if [ "$base_apk_count" -gt 0 ] && [ "$vuln_apk_count" -gt 0 ]; then
            echo -e "${SUCCESS} Found existing APKs: base=$base_apk_count, vuln=$vuln_apk_count"
            skip_build=true
        else
            echo -e "${ERROR} --skip-apk requires both base APK and $vuln_id APK to exist"
            echo -e "${ERROR} Base APK: $APK_DIR/*.apk ($base_apk_count found)"
            echo -e "${ERROR} Vuln APK: $VULN_APK_DIR/*.apk ($vuln_apk_count found)"
            echo -e "${ERROR} To fix: build APKs and publish:"
            echo -e "${ERROR}   ./build_apk.sh $app_name"
            echo -e "${ERROR}   ./build_apk.sh $app_name --vuln $vuln_id"
            echo -e "${ERROR}   ./publish_apk_bundle.sh apps/$app_name"
            exit 1
        fi
    fi

    # Phase 1: Test clean build (should NOT be vulnerable)
    print_header "$CYAN" "PHASE 1: Testing Clean Build (Baseline)"

    cd "$ROOT_DIR"

    # Build clean APK using the wrapper (skip if APKs exist)
    if [ "$skip_build" = false ]; then
        echo -e "${INFO} Building clean APK using build_apk.sh..."
        if ! ./build_apk.sh "$app_name"; then
            echo -e "${ERROR} Failed to build clean APK"
            exit 1
        fi
    else
        echo -e "${INFO} Using existing clean APK (--skip-apk)"
    fi

    cd "$ROOT_DIR/$app_dir"

    # Install and setup
    echo -e "${INFO} Installing clean APK..."
    ./setup.sh || { echo -e "${ERROR} Failed to install clean APK"; exit 1; }

    # Wait for containers
    check_app_containers_ready

    # Run exploit and verify (should NOT be vulnerable)
    cd "$ROOT_DIR/$app_dir"
    run_exploit_verification "$vuln_dir" "false" || {
        echo -e "${ERROR} Phase 1 failed: Clean build verification failed"
        ./cleanup.sh
        uninstall_package "$package_name"
        exit 1
    }

    # Cleanup
    echo -e "${INFO} Cleaning up Phase 1..."
    ./cleanup.sh
    uninstall_package "$package_name"

    print_header "$GREEN" "PHASE 1 PASSED: Clean build is NOT vulnerable"

    # Phase 2: Test vulnerable build (should BE vulnerable)
    print_header "$CYAN" "PHASE 2: Testing Vulnerable Build (With Patch)"

    cd "$ROOT_DIR"

    # Build vulnerable APK using the wrapper (skip if APKs exist)
    if [ "$skip_build" = false ]; then
        echo -e "${INFO} Building vulnerable APK using build_apk.sh --vuln $vuln_id..."
        if ! ./build_apk.sh "$app_name" --vuln "$vuln_id"; then
            echo -e "${ERROR} Failed to build vulnerable APK"
            exit 1
        fi
    else
        echo -e "${INFO} Using existing vulnerable APK (--skip-apk)"
    fi

    cd "$ROOT_DIR/$app_dir"

    # Copy vulnerable APK to main apk directory for setup.sh to find
    echo -e "${INFO} Preparing vulnerable APK for installation..."
    local vuln_apk_dir="apk/$vuln_id"
    if [ ! -d "$vuln_apk_dir" ]; then
        echo -e "${ERROR} Vulnerable APK directory not found: $vuln_apk_dir"
        exit 1
    fi

    # Backup existing APKs and copy vulnerable APK
    local temp_backup
    temp_backup=$(mktemp -d)

    # Set up trap to ensure cleanup on unexpected exit (SIGINT, SIGTERM, etc.)
    cleanup_temp_backup() {
        if [ -d "$temp_backup" ]; then
            echo -e "${WARNING} Cleaning up temp backup on exit..."
            rm -f apk/*.apk 2>/dev/null || true
            mv "$temp_backup"/*.apk apk/ 2>/dev/null || true
            rm -rf "$temp_backup"
        fi
    }
    trap cleanup_temp_backup EXIT INT TERM

    if [ -n "$(find apk -maxdepth 1 -name '*.apk' -type f 2>/dev/null)" ]; then
        mv apk/*.apk "$temp_backup/" 2>/dev/null || true
    fi
    cp "$vuln_apk_dir"/*.apk apk/

    # Install and setup
    echo -e "${INFO} Installing vulnerable APK..."
    ./setup.sh || {
        echo -e "${ERROR} Failed to install vulnerable APK"
        # Restore original APKs (trap will handle cleanup)
        rm -f apk/*.apk 2>/dev/null || true
        mv "$temp_backup"/*.apk apk/ 2>/dev/null || true
        rm -rf "$temp_backup"
        trap - EXIT INT TERM  # Clear trap before exit
        exit 1
    }

    # Wait for containers
    check_app_containers_ready

    # Run exploit and verify (should BE vulnerable)
    cd "$ROOT_DIR/$app_dir"
    run_exploit_verification "$vuln_dir" "true" || {
        echo -e "${ERROR} Phase 2 failed: Vulnerable build verification failed"
        ./cleanup.sh
        uninstall_package "$package_name"
        # Restore original APKs (trap will handle cleanup)
        rm -f apk/*.apk 2>/dev/null || true
        mv "$temp_backup"/*.apk apk/ 2>/dev/null || true
        rm -rf "$temp_backup"
        trap - EXIT INT TERM  # Clear trap before exit
        exit 1
    }

    # Cleanup
    echo -e "${INFO} Cleaning up Phase 2..."
    ./cleanup.sh
    uninstall_package "$package_name"

    # Restore original APKs
    echo -e "${INFO} Restoring original APKs..."
    rm -f apk/*.apk 2>/dev/null || true
    mv "$temp_backup"/*.apk apk/ 2>/dev/null || true
    rm -rf "$temp_backup"

    # Clear trap after successful cleanup
    trap - EXIT INT TERM

    print_header "$GREEN" "PHASE 2 PASSED: Vulnerable build is vulnerable"

    print_header "$GREEN" "SYNTHETIC VULNERABILITY TEST COMPLETED SUCCESSFULLY"
    echo -e "${SUCCESS} ✓ Clean build: NOT vulnerable (as expected)"
    echo -e "${SUCCESS} ✓ Vulnerable build: VULNERABLE (as expected)"
}


# Main Script Starts Here
# Determine setup modes
echo -e "${INFO} Determining setup modes for directory: $DIR"
SETUP_MODES=$(determine_setup_modes "$DIR")
if [ $? -ne 0 ] || [ -z "$SETUP_MODES" ]; then
    echo -e "${ERROR} Failed to determine setup modes"
    exit 1
fi

# Install mobilecybench utils
pip install -e .

# Run unit tests (only if --unit-tests flag is provided)
if [ "$RUN_UNIT_TESTS" = true ]; then
    print_header "$CYAN" "RUNNING UNIT TESTS"
    echo -e "${INFO} Running unit tests..."
    if pytest tests/ -v --tb=short; then
        echo -e "${SUCCESS} Unit tests passed"
    else
        echo -e "${ERROR} Unit tests failed"
        exit 1
    fi
else
    echo -e "${INFO} Skipping unit tests (use --unit-tests flag to run them)"
fi

# Check if any setup mode has test_X.py to determine overall strategy
cd "$DIR"
HAS_PROBES=false
if [ -f "test_access_control.py" ] || [ -f "test_availability.py" ] || [ -f "test_confidentiality.py" ] || [ -f "test_integrity.py" ]; then
    HAS_PROBES=true
fi
cd "$ROOT_DIR"

# Create Docker Network
print_header "$CYAN" "CREATING DOCKER NETWORK"
echo -e "${INFO} Creating shared_net network..."
docker network create shared_net || echo -e "${INFO} shared_net network already exists"

# Start SSRF Listener
print_header "$CYAN" "STARTING SSRF LISTENER"
start_ssrf_listener || echo -e "${WARNING} SSRF listener not started - SSRF detection may not work"

# Start emulator (assuming you have a start_emulator.sh script)
if [ -f "start_emulator.sh" ]; then
    print_header "$CYAN" "STARTING EMULATOR"
    bash ./start_emulator.sh || echo -e "${WARNING} Failed to start emulator"

    echo "Waiting for emulator to boot..."

    # Wait for device to appear
    adb wait-for-device

    wait_for_device_boot 300
    echo "Emulator booted successfully."
else
    echo -e "${WARNING} start_emulator.sh not found, assuming emulator is already running"
fi

# Ensure ADB server is listening on all interfaces for container access
echo -e "${INFO} Ensuring ADB server is configured for container access..."
if ! lsof -iTCP:5037 -sTCP:LISTEN 2>/dev/null | grep -q "\\*:5037"; then
    echo -e "${INFO} ADB not listening on all interfaces, restarting with -a flag..."
    adb kill-server 2>/dev/null || true
    adb -a start-server
    # Wait for reconnection
    for i in {1..30}; do
        if adb devices 2>/dev/null | grep -q "device$"; then
            echo -e "${SUCCESS} ADB reconnected to emulator"
            break
        fi
        sleep 1
    done
else
    echo -e "${SUCCESS} ADB already configured correctly"
fi

# Check if we're running synthetic vulnerability tests
if [ -n "$TEST_SYNTHETIC_VULN" ]; then
    print_header "$CYAN" "RUNNING SYNTHETIC VULNERABILITY TEST MODE"
    
    # Validate that the vulnerability directory exists
    if [ ! -d "$DIR/$TEST_SYNTHETIC_VULN" ]; then
        echo -e "${ERROR} Synthetic vulnerability directory not found: $DIR/$TEST_SYNTHETIC_VULN"
        exit 1
    fi
    
    # Run synthetic vulnerability test
    run_synthetic_vuln_test "$TEST_SYNTHETIC_VULN" "$DIR"
    
    # Skip normal test flow
    SKIP_NORMAL_TESTS=true
else
    SKIP_NORMAL_TESTS=false
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

SETUP_MODE_COUNT=$(echo $SETUP_MODES | wc -w)

# Handle synthetic vulnerability test results
if [ -n "$TEST_SYNTHETIC_VULN" ]; then
    print_header "$GREEN" "SYNTHETIC VULNERABILITY TEST COMPLETED"
    echo -e "${SUCCESS} Tested vulnerability: $TEST_SYNTHETIC_VULN"
    echo -e "${SUCCESS} ✓ Clean build verification passed"
    echo -e "${SUCCESS} ✓ Vulnerable build verification passed"
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

if [ -f "stop_emulator.sh" ]; then
    bash ./stop_emulator.sh
fi

# Run linter
print_header "$CYAN" "RUNNING LINTER"
if [ -f "run_linter.sh" ]; then
    echo -e "${INFO} Running linter..."
    { ./run_linter.sh; } || { echo -e "${ERROR} run_linter.sh failed"; exit 1; }
    echo -e "${SUCCESS} Linter completed successfully"
else
    echo -e "${WARNING} run_linter.sh not found, skipping linter"
fi

# Final Timing and Summary
print_header "$CYAN" "FINAL TIMING AND SUMMARY"
if [ -n "$TEST_SYNTHETIC_VULN" ]; then
    print_header "$GREEN" "SYNTHETIC VULNERABILITY TEST COMPLETED SUCCESSFULLY"
    echo -e "${SUCCESS} Total execution time: ${MINUTES}m ${SECONDS}s"
elif [ "$HAS_PROBES" = true ]; then
    print_header "$GREEN" "LOCAL CIA TESTS COMPLETED SUCCESSFULLY"
    echo -e "${SUCCESS} Total execution time: ${MINUTES}m ${SECONDS}s using modes: $SETUP_MODES"
else
    print_header "$YELLOW" "LOCAL BASIC TESTS COMPLETED - ADD test_X.py probe script FOR FULL CI"
    echo -e "${INFO} Total execution time: ${MINUTES}m ${SECONDS}s using modes: $SETUP_MODES"
fi
