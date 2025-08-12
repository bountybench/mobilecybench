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

checkout_commit() {
    pwd
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
ROOT_DIR=$(pwd)
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
    echo -e "${WARNING} Could not extract SDK from $metadata. Using default (28)."
    sdk=28
else 
    echo -e "${INFO} SDK: $sdk"
fi

print_header "$CYAN" "STARTING LOCAL CIA TESTS"

# Function to run test checks
run_test_check() {
    local test_name="$1"
    local vuln_scenario="$2"
    local use_log_file="$3"

    print_header "$CYAN" "RUNNING $test_name"

    cd "$ROOT_DIR"    
    cd "$DIR"
    checkout_commit "$DIR"

    required_scripts=("setup.sh" "run_checks.sh" "cleanup.sh")
    echo -e "${INFO} Checking for required scripts..."
    for script in "${required_scripts[@]}"; do
        if [[ ! -f "$script" ]]; then
            echo -e "${ERROR} Required script '$script' not found."
            exit 1
        fi
    done

    echo -e "${INFO} Running setup..."
    ./setup.sh
    adb logcat -c

    if [ -n "$vuln_scenario" ]; then
        echo -e "${INFO} Creating vulnerable scenario $vuln_scenario..."
        cd "vuln_scenarios/vuln_scenario_$vuln_scenario"
        ./vuln.sh
        cd -
    fi

    echo -e "${INFO} Running checks..."
    if [ "$use_log_file" = "true" ] && [ -n "$vuln_scenario" ]; then
        ./run_checks.sh "vuln_scenarios/vuln_scenario_$vuln_scenario/fake_agent_log.log"
    else
        ./run_checks.sh
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

# Start emulator (assuming you have a start_emulator.sh script)
if [ -f "start_emulator.sh" ]; then
    print_header "$CYAN" "STARTING EMULATOR"
    ./start_emulator.sh > /dev/null 2>&1 &
    EMULATOR_PID=$!

    echo "Waiting for emulator to boot..."

    # Wait for device to appear
    adb wait-for-device

    # Wait until system property `sys.boot_completed` returns 1
    boot_completed=""
    while [ "$boot_completed" != "1" ]; do
        boot_completed=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
        sleep 1
    done

    echo "Emulator booted successfully."
    
    # Wait for servers to be ready
    check_server_ready
else
    echo -e "${WARNING} start_emulator.sh not found, assuming emulator is already running"
fi

cd $ROOT_DIR
# Run the three test scenarios
run_test_check "TEST CHECKS BEFORE VULNERABLE SCENARIOS" "" "false"
run_test_check "TEST CHECKS AFTER NON-DOS VULNERABLE SCENARIO" "0" "true"
run_test_check "TEST CHECKS AFTER DOS VULNERABLE SCENARIO" "1" "false"

print_header "$GREEN" "ALL TESTS PASSED"

# Stop emulator
if [ -n "$EMULATOR_PID" ]; then
    print_header "$CYAN" "STOPPING EMULATOR"
    if [ -f "stop_emulator.sh" ]; then
        ./stop_emulator.sh
    else
        kill $EMULATOR_PID 2>/dev/null || true
    fi
fi

# Final cleanup
print_header "$CYAN" "FINAL CLEANUP"
print_header "$GREEN" "LOCAL CIA TESTS COMPLETED SUCCESSFULLY"