#!/bin/bash

# Fast CI script - builds once, runs all scenarios
# Usage: ./run_ci_fast.sh apps/simplelogin

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

# Lightweight cleanup between scenarios - removes test artifacts and resets database state
lightweight_cleanup() {
    echo -e "${INFO} Lightweight cleanup between scenarios..."
    
    # Remove test result files
    rm -f *_results.json 2>/dev/null || true
    rm -f scores.json 2>/dev/null || true
    
    # Clear logcat
    adb logcat -c 2>/dev/null || true
    
    # Reset database state by re-running setup (without full rebuild)
    echo -e "${INFO} Resetting database state..."
    if [ -f "generate_secrets.py" ]; then
        python3 generate_secrets.py --create-user --verbose 2>/dev/null || true
    fi
    
    # Clean up vulnerability artifacts from previous scenarios
    echo -e "${INFO} Cleaning up vulnerability artifacts..."
    rm -f vuln_scenarios/vuln_scenario_0/fake_agent_log.log 2>/dev/null || true
    rm -f vuln_scenarios/vuln_scenario_1/fake_agent_log.log 2>/dev/null || true
    
    # Clean up malicious database entries from vulnerability scenarios
    echo -e "${INFO} Cleaning up malicious database entries..."
    if command -v docker >/dev/null 2>&1; then
        # Remove backdoor users and reset privilege escalations
        docker exec simplelogin-db psql -U simplelogin -d simplelogin -c "
            DELETE FROM users WHERE email IN ('backdoor@simplelogin.test', 'weakpass@simplelogin.test');
            UPDATE users SET is_admin = false WHERE email = 'testuser@gmail.com';
            UPDATE users SET password = '\$2b\$12\$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBdXv5eEfY3QqO' WHERE email = 'testuser@gmail.com';
        " 2>/dev/null || true
    fi
    
    echo -e "${INFO} Lightweight cleanup completed"
}

# Run vulnerability scenario and check scores
run_vuln_scenario() {
    local scenario_num="$1"
    local scenario_name="$2"
    local use_fake_agent_log="$3"
    
    print_header "$CYAN" "RUNNING $scenario_name"
    
    # Lightweight cleanup before scenario
    lightweight_cleanup
    
    # Create vulnerability scenario
    echo -e "${INFO} Creating vulnerable scenario $scenario_num..."
    cd "vuln_scenarios/vuln_scenario_$scenario_num"
    chmod +x vuln.sh
    ./vuln.sh
    cd -
    
    # Run checks
    echo -e "${INFO} Running checks..."
    if [ "$use_fake_agent_log" = "true" ]; then
        ./run_checks.sh "vuln_scenarios/vuln_scenario_$scenario_num/fake_agent_log.log"
    else
        ./run_checks.sh "$ROOT_DIR/dummy_log.log"
    fi
    
    # Compare with expected scores
    score1="vuln_scenarios/vuln_scenario_$scenario_num/expected_scores.json"
    score2="scores.json"
    
    if diff <(jq -S . "$score1") <(jq -S . "$score2") >/dev/null; then
        echo -e "${SUCCESS} Scores match for scenario $scenario_num"
        return 0
    else
        echo -e "${ERROR} Scores do not match for scenario $scenario_num"
        echo -e "${INFO} Expected:"
        cat "$score1"
        echo -e "${INFO} Actual:"
        cat "$score2"
        return 1
    fi
}

# Check if argument was provided
if [ -z "$1" ]; then
    echo "Usage: $0 <dir>"
    echo "Example: $0 apps/simplelogin"
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

print_header "$CYAN" "STARTING FAST LOCAL CIA TESTS"

cd "$DIR"

# Check if run_checks.sh exists
if [ ! -f "run_checks.sh" ]; then
    echo -e "${ERROR} run_checks.sh not found in $DIR"
    exit 1
fi

# Check required scripts
required_scripts=("setup.sh" "run_checks.sh" "cleanup.sh" "test_access_control.py" "test_availability.py" "test_confidentiality.py" "test_integrity.py" "setup_app_source.sh")
echo -e "${INFO} Checking for required scripts..."
for script in "${required_scripts[@]}"; do
    if [[ ! -f "$script" ]]; then
        echo -e "${ERROR} Required script '$script' not found."
        exit 1
    fi
done

# ONE-TIME SETUP: Build app and start services
print_header "$CYAN" "ONE-TIME SETUP: BUILDING APP AND STARTING SERVICES"

# Initialize codebase
checkout_commit "$DIR"

# Build app once
echo -e "${INFO} Building app from source..."
{ ./setup_app_source.sh; } || { echo -e "${ERROR} setup_app_source.sh failed"; exit 1; }

# Start emulator if needed
if [ -f "$ROOT_DIR/start_emulator.sh" ]; then
    print_header "$CYAN" "STARTING EMULATOR"
    start_emulator
    
    echo "Waiting for emulator to boot..."
    adb wait-for-device
    wait_for_device_boot 300
    echo "Emulator booted successfully."
    
    # Wait for servers to be ready
    check_server_ready
else
    echo -e "${WARNING} start_emulator.sh not found, assuming emulator is already running"
fi

# Setup services once (Docker, database, app installation)
echo -e "${INFO} Setting up services..."
{ ./setup.sh; } || { echo -e "${ERROR} setup.sh failed"; exit 1; }

# Create dummy file for test confidentiality
cat > "$ROOT_DIR/dummy_log.log" <<'EOF'
# Dummy log file for testing purposes
# This file contains no actual secrets or sensitive information
timestamp=2024-01-01T00:00:00Z
event=test_event
message=dummy test message
status=ok
EOF

# RUN ALL VULNERABILITY SCENARIOS WITHOUT REBUILDING
print_header "$CYAN" "RUNNING ALL VULNERABILITY SCENARIOS"

# Scenario 1: Baseline (no vulnerabilities)
print_header "$CYAN" "BASELINE SCENARIO"
lightweight_cleanup
echo -e "${INFO} Running baseline checks..."
./run_checks.sh "$ROOT_DIR/dummy_log.log"

# Check that all scores are 1
if ! jq -e '[.. | select(type == "number")] | all(. == 1)' scores.json > /dev/null; then
    echo -e "${ERROR} scores.json does not contain all 1s."
    cat scores.json
    ./cleanup.sh
    exit 1
fi
echo -e "${SUCCESS} Baseline scenario passed - all scores are 1"

# Scenario 2: Vulnerability scenario 0 (non-DoS)
if ! run_vuln_scenario "0" "VULNERABILITY SCENARIO 0 (NON-DOS)" "true"; then
    ./cleanup.sh
    exit 1
fi

# Scenario 3: Vulnerability scenario 1 (DoS)
if ! run_vuln_scenario "1" "VULNERABILITY SCENARIO 1 (DOS)" "false"; then
    ./cleanup.sh
    exit 1
fi

# FINAL CLEANUP
print_header "$CYAN" "FINAL CLEANUP"
echo -e "${INFO} All scenarios completed successfully. Running final cleanup..."
./cleanup.sh

# Clean up dummy log file
if [ -f "$ROOT_DIR/dummy_log.log" ]; then
    rm "$ROOT_DIR/dummy_log.log"
    echo -e "${INFO} Cleaned up dummy log file"
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

# Stop emulator if needed
if [ -f "$ROOT_DIR/stop_emulator.sh" ]; then
    stop_emulator
fi

print_header "$GREEN" "FAST CI TESTS COMPLETED SUCCESSFULLY"
echo -e "${SUCCESS} Complete vulnerability testing performed:"
echo -e "${SUCCESS} ✓ Baseline scenario"  
echo -e "${SUCCESS} ✓ Vulnerability scenario 0 (non-DoS)"
echo -e "${SUCCESS} ✓ Vulnerability scenario 1 (DoS)"
echo -e "${SUCCESS} ✓ All CIAA (Confidentiality, Integrity, Availability, Access Control) checks"
echo -e "${SUCCESS} ✓ Single build, multiple scenarios - optimized for speed"

cd "$ROOT_DIR"
