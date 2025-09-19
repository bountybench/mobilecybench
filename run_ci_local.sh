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

determine_setup_mode() {
    local dir="$1"
    local setup_mode="source"  # default to source
    
    # Check for both setup scripts
    local has_source=false
    local has_apklink=false

    if [ -f "$dir/setup_app_source.sh" ]; then
        has_source=true
        echo -e "${INFO} Found setup_app_source.sh" >&2
    fi
    
    if [ -f "$dir/setup_app_apklink.sh" ]; then
        has_apklink=true
        echo -e "${INFO} Found setup_app_apklink.sh" >&2
    fi
    
    # Validate at least one exists
    if [ "$has_source" = false ] && [ "$has_apklink" = false ]; then
        echo -e "${ERROR} Neither setup_app_source.sh nor setup_app_apklink.sh found in $dir" >&2
        exit 1
    fi
    
    # Determine preference based on what scripts exist
    if [ "$has_source" = true ] && [ "$has_apklink" = true ]; then
        # Both scripts exist - check for modifications
        # Find the remote that points to bountybench/mobilecybench.git
        bountybench_remote=""
        while IFS= read -r line; do
            remote_name=$(echo "$line" | awk '{print $1}')
            remote_url=$(echo "$line" | awk '{print $2}')
            if [[ "$remote_url" == *"bountybench/mobilecybench"* ]]; then
                bountybench_remote="$remote_name"
                break
            fi
        done < <(git remote -v | grep "(fetch)")
        
        if [ -n "$bountybench_remote" ]; then
            echo -e "${INFO} Found bountybench remote: $bountybench_remote" >&2
            # Fetch the latest main branch from bountybench remote
            git fetch "$bountybench_remote" main >/dev/null 2>&1 || true
            # Check for modifications against bountybench main - only for this specific app
            if git diff --name-only "$bountybench_remote/main...HEAD" | grep -E "^$dir/setup_app_(source|apklink)\.sh$" >/dev/null 2>&1; then
                echo -e "${INFO} Setup script changes detected - using source build for thorough testing" >&2
                setup_mode="source"
            else
                echo -e "${INFO} Both scripts available and unmodified - preferring APK link for efficiency" >&2
                setup_mode="apklink"
            fi
        else
            echo -e "${WARNING} Could not find bountybench remote - falling back to source mode" >&2
            setup_mode="source"
        fi
    elif [ "$has_source" = true ] && [ "$has_apklink" = false ]; then
        echo -e "${INFO} Only source setup available - using source mode" >&2
        setup_mode="source"
    elif [ "$has_source" = false ] && [ "$has_apklink" = true ]; then
        echo -e "${INFO} Only APK link setup available - using apklink mode" >&2
        setup_mode="apklink"
    fi
    echo "$setup_mode"
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

# Check if argument was provided
if [ -z "$1" ]; then
    echo "Usage: $0 <dir>"
    echo "Example: $0 apps/joplin"
    exit 1
fi
DIR="$1"

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

    echo -e "${INFO} Running setup..."
    { ./setup.sh; } || { echo -e "${ERROR} setup.sh failed"; exit 1; }
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
        ./run_checks.sh "vuln_scenarios/vuln_scenario_$vuln_scenario/fake_agent_log.log"
    else
        ./run_checks.sh "$ROOT_DIR/dummy_log.log"
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
    fi

    echo -e "${INFO} Cleaning up..."
    ./cleanup.sh
    cd -
}

# Determine setup mode
echo -e "${INFO} Determining setup mode for directory: $DIR"
SETUP_MODE=$(determine_setup_mode "$DIR")
if [ $? -ne 0 ] || [ -z "$SETUP_MODE" ]; then
    echo -e "${ERROR} Failed to determine setup mode"
    exit 1
fi
echo -e "${INFO} Selected setup mode: $SETUP_MODE"

cd "$DIR"

# Skip this step if you want to persist your apk
checkout_commit "$DIR"

# Check if run_checks.sh exists to determine test strategy and required scripts
if [ -f "run_checks.sh" ]; then
    echo -e "${INFO} run_checks.sh found - running full vulnerability scenario tests"
    HAS_RUN_CHECKS=true
    if [ "$SETUP_MODE" = "apklink" ]; then
        required_scripts=("setup.sh" "run_checks.sh" "cleanup.sh" "test_access_control.py" "test_availability.py" "test_confidentiality.py" "test_integrity.py" "setup_app_apklink.sh")
        print_header "$CYAN" "SETTING UP APP FROM APK LINK"
    else
        required_scripts=("setup.sh" "run_checks.sh" "cleanup.sh" "test_access_control.py" "test_availability.py" "test_confidentiality.py" "test_integrity.py" "setup_app_source.sh")
        print_header "$CYAN" "SETTING UP APP FROM SOURCE"
    fi
else
    echo -e "${INFO} run_checks.sh not found - running simplified APK installation test"
    HAS_RUN_CHECKS=false
    if [ "$SETUP_MODE" = "apklink" ]; then
        required_scripts=("setup.sh" "cleanup.sh" "setup_app_apklink.sh")
        print_header "$CYAN" "SETTING UP APP FROM APK LINK"
    else
        required_scripts=("setup.sh" "cleanup.sh" "setup_app_source.sh")
        print_header "$CYAN" "SETTING UP APP FROM SOURCE"
    fi
fi

echo -e "${INFO} Checking for required scripts..."
for script in "${required_scripts[@]}"; do
    if [[ ! -f "$script" ]]; then
        echo -e "${ERROR} Required script '$script' not found."
        exit 1
    fi
done

# Run appropriate setup script based on mode
if [ "$SETUP_MODE" = "apklink" ]; then
    echo -e "${INFO} Setting up app from APK link."
    { ./setup_app_apklink.sh; } || { echo -e "${ERROR} setup_app_apklink.sh failed"; exit 1; }
else
    echo -e "${INFO} Setting up app from source..."
    { ./setup_app_source.sh; } || { echo -e "${ERROR} setup_app_source.sh failed"; exit 1; }
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

if [ "$HAS_RUN_CHECKS" = true ]; then
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
    run_test_check "TEST CHECKS AFTER DOS VULNERABLE SCENARIO" "1" "false"
else
    # Run simplified test
    print_header "$CYAN" "RUNNING SIMPLIFIED APK INSTALLATION TEST"
    
    cd "$ROOT_DIR"
    cd "$DIR"

    echo -e "${INFO} Simple APK build and install test - no vulnerability scenarios"
    
    # Check packages before setup
    packages_before=$(adb shell pm list packages | wc -l)
    echo -e "${INFO} Packages before setup: $packages_before"
    
    echo -e "${INFO} Running setup..."
    { ./setup.sh; } || { echo -e "${ERROR} setup.sh failed"; exit 1; }
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

# Calculate total runtime
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
MINUTES=$((DURATION / 60))
SECONDS=$((DURATION % 60))

if [ "$HAS_RUN_CHECKS" = true ]; then
    print_header "$GREEN" "ALL TESTS PASSED"
    print_header "$GREEN" "FULL CI COMPLETED SUCCESSFULLY"
    echo -e "${SUCCESS} Complete vulnerability testing performed:"
    echo -e "${SUCCESS} ✓ Baseline scenario"  
    echo -e "${SUCCESS} ✓ Vulnerability scenario 0 (non-DoS)"
    echo -e "${SUCCESS} ✓ Vulnerability scenario 1 (DoS)"
    echo -e "${SUCCESS} ✓ All CIAA (Confidentiality, Integrity, Availability, Access Control) checks"
    echo -e "${INFO} Total runtime: ${MINUTES}m ${SECONDS}s (Setup mode: $SETUP_MODE)"
else
    print_header "$GREEN" "BASIC TESTS PASSED"
    print_header "$YELLOW" "SIMPLIFIED CI COMPLETED - FULL CI NOT RUN"
    echo ""
    echo -e "${WARNING} ⚠️  IMPORTANT: Only basic APK installation testing was performed"
    echo -e "${WARNING} ⚠️  Full vulnerability scenario testing was NOT run"
    echo ""  
    echo -e "${INFO} To enable full CI testing, this app needs:"
    echo -e "${INFO} • run_checks.sh script"
    echo -e "${INFO} • Vulnerability scenario implementations"
    echo -e "${INFO} • Full CIAA security test coverage"
    echo ""
    echo -e "${CYAN} The GitHub CI will also run in simplified mode for this app"
    echo -e "${CYAN} until run_checks.sh is added."
    echo -e "${INFO} Total runtime: ${MINUTES}m ${SECONDS}s (Setup mode: $SETUP_MODE)"
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

# Final cleanup
print_header "$CYAN" "FINAL CLEANUP"
if [ "$HAS_RUN_CHECKS" = true ]; then
    # Clean up dummy log file
    if [ -f "$ROOT_DIR/dummy_log.log" ]; then
        rm "$ROOT_DIR/dummy_log.log"
        echo -e "${INFO} Cleaned up dummy log file"
    fi
    print_header "$GREEN" "LOCAL CIA TESTS COMPLETED SUCCESSFULLY"
    echo -e "${SUCCESS} Total execution time: ${MINUTES}m ${SECONDS}s using $SETUP_MODE mode"
else
    print_header "$YELLOW" "LOCAL BASIC TESTS COMPLETED - ADD run_checks.sh FOR FULL CI"
    echo -e "${INFO} Total execution time: ${MINUTES}m ${SECONDS}s using $SETUP_MODE mode"
fi