#!/bin/bash

# SimpleLogin CIAA Checks Runner
# Executes all security tests and generates scores.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_FILE="$SCRIPT_DIR/scores.json"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_prerequisites() {
    log_info "Checking prerequisites for CIAA tests..."
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_error "python3 not found. Please install Python 3."
        return 1
    fi
    
    # Check required Python packages
    local required_packages=("requests")
    for package in "${required_packages[@]}"; do
        if ! python3 -c "import $package" 2>/dev/null; then
            log_warning "Installing required Python package: $package"
            pip3 install "$package" || {
                log_error "Failed to install $package"
                return 1
            }
        fi
    done
    
    # Check that setup has been run
    if [[ ! -f "$SCRIPT_DIR/secrets.json" ]]; then
        log_error "secrets.json not found. Please run setup.sh first."
        return 1
    fi
    
    log_success "Prerequisites check passed"
}

run_test() {
    local test_name="$1"
    local test_script="$2"
    local test_file="$SCRIPT_DIR/$test_script"
    
    log_info "Running $test_name test..."
    
    if [[ ! -f "$test_file" ]]; then
        log_error "Test file not found: $test_file"
        return 1
    fi
    
    # Make script executable
    chmod +x "$test_file"
    
    # Run the test and capture output
    local test_output
    local test_exit_code
    
    test_output=$(python3 "$test_file" 2>&1) || test_exit_code=$?
    test_exit_code=${test_exit_code:-0}
    
    echo "$test_output"
    
    if [[ $test_exit_code -eq 0 ]]; then
        log_success "$test_name test completed successfully"
        return 0
    else
        log_warning "$test_name test completed with warnings/failures"
        return 1
    fi
}

collect_results() {
    log_info "Collecting test results..."
    
    local results="{}"
    local total_score=0
    local test_count=0
    
    # Collect results from individual test files
    local result_files=(
        "confidentiality_results.json"
        "integrity_results.json" 
        "availability_results.json"
        "access_control_results.json"
    )
    
    for result_file in "${result_files[@]}"; do
        local file_path="$SCRIPT_DIR/$result_file"
        
        if [[ -f "$file_path" ]]; then
            local test_results
            test_results=$(cat "$file_path")
            
            # Extract the main score key (first key that ends with score or matches CIAA)
            local score_key
            score_key=$(echo "$test_results" | jq -r 'keys[] | select(. | test("(confidentiality|integrity|availability|access_control)"))' | head -1)
            
            if [[ -n "$score_key" && "$score_key" != "null" ]]; then
                local score
                score=$(echo "$test_results" | jq -r ".$score_key")
                
                if [[ "$score" != "null" && "$score" =~ ^[0-9]+\.?[0-9]*$ ]]; then
                    results=$(echo "$results" | jq --arg key "$score_key" --argjson value "$score" '. + {($key): $value}')
                    total_score=$(echo "$total_score + $score" | bc -l)
                    ((test_count++))
                fi
            fi
        else
            log_warning "Result file not found: $file_path"
        fi
    done
    
    # Calculate overall score
    local overall_score
    if [[ $test_count -gt 0 ]]; then
        overall_score=$(echo "scale=2; $total_score / $test_count" | bc -l)
    else
        overall_score="0.0"
    fi
    
    # Add overall score and metadata
    results=$(echo "$results" | jq --argjson overall "$overall_score" --argjson count "$test_count" '. + {
        "overall_score": $overall,
        "tests_run": $count,
        "timestamp": now,
        "app_name": "SimpleLogin"
    }')
    
    # Write final results
    echo "$results" | jq '.' > "$RESULTS_FILE"
    
    log_success "Results collected in $RESULTS_FILE"
    
    # Display summary
    echo
    echo "=" * 50
    echo "FINAL RESULTS SUMMARY"
    echo "=" * 50
    echo "Overall Score: $overall_score"
    echo "Tests Run: $test_count"
    echo
    echo "Individual Scores:"
    echo "$results" | jq -r 'to_entries[] | select(.key | test("(confidentiality|integrity|availability|access_control)")) | "\(.key | split("_")[0] | ascii_upcase): \(.value)"'
    echo "=" * 50
}

main() {
    log_info "Starting SimpleLogin CIAA security tests..."
    
    check_prerequisites
    
    # Run all CIAA tests
    local tests=(
        "Confidentiality:test_confidentiality.py"
        "Integrity:test_integrity.py"
        "Availability:test_availability.py"
        "Access Control:test_access_control.py"
    )
    
    local passed_tests=0
    local total_tests=${#tests[@]}
    
    for test_info in "${tests[@]}"; do
        IFS=':' read -r test_name test_script <<< "$test_info"
        
        echo
        echo "=" * 60
        
        if run_test "$test_name" "$test_script"; then
            ((passed_tests++))
        fi
        
        echo "=" * 60
    done
    
    echo
    log_info "All tests completed. Collecting results..."
    
    collect_results
    
    log_success "CIAA security tests completed!"
    log_info "Passed: $passed_tests/$total_tests tests"
    log_info "Results file: $RESULTS_FILE"
    
    # Exit with success if majority of tests passed
    if [[ $passed_tests -ge $((total_tests / 2)) ]]; then
        exit 0
    else
        exit 1
    fi
}

# Run main function if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
