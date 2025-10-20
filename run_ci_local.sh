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

check_server_ready() {
    # Timeout per container in seconds
    TIMEOUT=${TIMEOUT:-180}
    # Interval between checks in seconds
    INTERVAL=${INTERVAL:-1}

    # Get all running containers
    containers=$(docker ps --format '{{.Names}}')

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

    echo "All containers are ready!"
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

# Validate directory structure and required scripts
validate_setup_app_scripts() {
    local dir="$1"
    
    if [ ! -d "$dir" ]; then
        echo -e "${ERROR} Directory '$dir' does not exist" >&2
        return 1
    fi
    
    local source_script="$dir/setup_app_source.sh"
    local apklink_script="$dir/setup_app_apklink.sh"
    if [ ! -f "$source_script" ] && [ ! -f "$apklink_script" ]; then
        # fail if neither script exists
        echo -e "${ERROR} No setup scripts found in $dir" >&2
        echo -e "${ERROR} Expected: setup_app_source.sh or setup_app_apklink.sh" >&2
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
        if [ -f "$dir/setup_app_apklink.sh" ]; then
            modes="$modes apklink"
            echo -e "${INFO} Found setup_app_apklink.sh (download mode)" >&2
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

# Parse command line arguments
SKIP_BUILD=false
SKIP_DOWNLOAD=false
SKIP_APK=false
RUN_UNIT_TESTS=false

show_usage() {
    echo "Usage: $0 <dir> [options]"
    echo ""
    echo "Arguments:"
    echo "  <dir>             Directory to test (e.g., apps/joplin)"
    echo ""
    echo "Options:"
    echo "  --skip-build      Skip build mode (source setup)"
    echo "  --skip-download   Skip download mode (apklink setup)"
    echo "  --skip-apk        Skip APK operations. Install from existing APK."
    echo "  --unit-tests      Run unit tests (opt-in)"
    echo "  -h, --help        Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 apps/joplin                   # Run both build and download modes"
    echo "  $0 apps/joplin --skip-build      # Run only download mode"
    echo "  $0 apps/joplin --skip-download   # Run only build mode"
    echo "  $0 apps/joplin --skip-apk        # Skip APK operations. Install from existing APK."
    echo "  $0 apps/joplin --unit-tests      # Run unit tests"
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

sdk=$(jq -r '.sdk' "$metadata")
if [ "$?" -ne 0 ] || [ "$sdk" = "null" ] || [ -z "$sdk" ]; then
    echo -e "${ERROR} Could not extract SDK from $metadata."
    exit 1
else 
    echo -e "${INFO} SDK: $sdk"
fi

print_header "$CYAN" "STARTING LOCAL CIA TESTS"

START_TIME=$(date +%s)

# Function to run test checks
run_test_check() {
    local test_name="$1"
    local vuln_scenario="$2"
    local use_fake_agent_log="$3"

    print_header "$CYAN" "RUNNING $test_name"

    cd "$ROOT_DIR"
    cd "$DIR"

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

    echo -e "${INFO} Running setup..."
    { ./setup.sh; } || { echo -e "${ERROR} setup.sh failed"; exit 1; }
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
    if [ "$use_fake_agent_log" = "true" ] && [ -n "$vuln_scenario" ]; then
        ../../run_checks.sh . "vuln_scenarios/vuln_scenario_$vuln_scenario/fake_agent_log.log"
    else
        ../../run_checks.sh . "$ROOT_DIR/dummy_log.log"
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
            exit 1
        fi
    else
        # Check that all scores are 1
        if ! jq -e '[.. | select(type == "number")] | all(. == 1)' scores.json > /dev/null; then
            echo -e "${ERROR} scores.json does not contain all 1s."
            cat scores.json
            echo -e "${INFO} Cleaning up..."
            ./cleanup.sh
            exit 1
        fi
        echo -e "${SUCCESS} All scores are 1."

        # Check that all generic scores are 1
        if ! jq -e '[.. | select(type == "number")] | all(. == 1)' generic_scores.json > /dev/null; then
            echo -e "${ERROR} generic_scores.json does not contain all 1s."
            cat generic_scores.json
            echo -e "${INFO} Cleaning up..."
            ./cleanup.sh
            exit 1
        fi
        echo -e "${SUCCESS} All generic scores are 1."
    fi

    echo -e "${INFO} Cleaning up..."
    ./cleanup.sh
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
        echo -e "${INFO} Skipping APK setup (apk_skip mode) - proceeding directly to setup.sh"
    elif [ "$setup_mode" = "apklink" ]; then
        echo -e "${INFO} Setting up app from APK link."
        { ./setup_app_apklink.sh; } || { echo -e "${ERROR} setup_app_apklink.sh failed"; exit 1; }
    else
        echo -e "${INFO} Setting up app from source..."
        { ./setup_app_source.sh; } || { echo -e "${ERROR} setup_app_source.sh failed"; exit 1; }
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
        echo -e "${ERROR} setup_app_source.sh or setup_app_apklink.sh must place APKs in ${dir}/apk/"
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
    else
        # Run simplified test
        print_header "$CYAN" "RUNNING SIMPLIFIED APK INSTALLATION TEST"
        
        cd "$ROOT_DIR"
        cd "$dir"
        
        echo -e "${INFO} Simple APK build and install test - no vulnerability scenarios"
        
        # Check packages before setup
        packages_before=$(adb shell pm list packages | wc -l)
        echo -e "${INFO} Packages before setup: $packages_before"
        
        echo -e "${INFO} Running setup..."
        { ./setup.sh; } || { echo -e "${ERROR} setup.sh failed"; exit 1; }
        echo -e "${INFO} Injecting flags..."
        { ../../inject_flags.sh; } || { echo -e "${ERROR} inject_flags.sh failed"; exit 1; }
        verify_shared_net_connectivity
        adb logcat -c
        
        # Check packages after setup
        packages_after=$(adb shell pm list packages | wc -l)
        echo -e "${INFO} Packages after setup: $packages_after"
        
        if [ "$packages_after" -gt "$packages_before" ]; then
            echo -e "${SUCCESS} Package count increased ($packages_before -> $packages_after) - app installation verified"
        elif [ "$packages_after" -eq "$packages_before" ]; then
            echo -e "${WARNING} Package count unchanged - setup may not have installed new packages"
            echo -e "${WARNING} This could be expected if app was already installed or uses system components"
        else
            echo -e "${ERROR} Package count decreased ($packages_before -> $packages_after) - unexpected behavior"
            echo -e "${INFO} Cleaning up..."
            ./cleanup.sh
            exit 1
        fi
        
        echo -e "${INFO} Cleaning up..."
        ./cleanup.sh
        cd -
    fi
    
    # Clean up dummy log file if it exists
    if [ -f "$ROOT_DIR/dummy_log.log" ]; then
        rm "$ROOT_DIR/dummy_log.log"
        echo -e "${INFO} Cleaned up dummy log file"
    fi
    
    print_header "$GREEN" "SETUP MODE $setup_mode COMPLETED SUCCESSFULLY"
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

# Start emulator (assuming you have a start_emulator.sh script)
if [ -f "start_emulator.sh" ]; then
    print_header "$CYAN" "STARTING EMULATOR"
    start_emulator

    echo "Waiting for emulator to boot..."

    # Wait for device to appear
    adb wait-for-device

    wait_for_device_boot 300
    echo "Emulator booted successfully."
    
    # Wait for servers to be ready
    check_server_ready
else
    echo -e "${WARNING} start_emulator.sh not found, assuming emulator is already running"
fi

# Run tests for each setup mode
for SETUP_MODE in $SETUP_MODES; do
    run_tests_for_mode "$SETUP_MODE" "$DIR"
done

# Calculate total runtime
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
MINUTES=$((DURATION / 60))
SECONDS=$((DURATION % 60))

SETUP_MODE_COUNT=$(echo $SETUP_MODES | wc -w)

if [ "$HAS_PROBES" = true ]; then
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
if [ -f "stop_emulator.sh" ]; then
    stop_emulator
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
if [ "$HAS_PROBES" = true ]; then
    print_header "$GREEN" "LOCAL CIA TESTS COMPLETED SUCCESSFULLY"
    prefix="${SUCCESS}"
else
    print_header "$YELLOW" "LOCAL BASIC TESTS COMPLETED - ADD test_X.py probe script FOR FULL CI"
    prefix="${INFO}"
fi

echo -e "${prefix} Total execution time: ${MINUTES}m ${SECONDS}s using modes: $SETUP_MODES"