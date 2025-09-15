#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_FILE="$SCRIPT_DIR/scores.json"

check_prerequisites() {
    echo "Checking prerequisites for CIAA tests..."
    
    # Check Python
    if ! command -v python3 &> /dev/null; then
        echo "ERROR:" "python3 not found. Please install Python 3."
        return 1
    fi
    
    # Check required Python packages
    local required_packages=("requests")
    for package in "${required_packages[@]}"; do
        if ! python3 -c "import $package" 2>/dev/null; then
            echo "Warning:" "Installing required Python package: $package"
            pip3 install "$package" || {
                echo "ERROR:" "Failed to install $package"
                return 1
            }
        fi
    done
    
    # Check that setup has been run
    if [[ ! -f "$SCRIPT_DIR/secrets.json" ]]; then
        echo "ERROR:" "secrets.json not found. Please run setup.sh first."
        return 1
    fi
    
    echo "Prerequisites check passed"
}

run_test() {
    local test_name="$1"
    local test_script="$2"
    local test_file="$SCRIPT_DIR/$test_script"
    
    echo "Running $test_name test..."
    
    if [[ ! -f "$test_file" ]]; then
        echo "ERROR:" "Test file not found: $test_file"
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
        echo "$test_name test completed successfully"
        return 0
    else
        echo "Warning:" "$test_name test completed with warnings/failures"
        return 1
    fi
}

collect_results() {
    echo "Collecting test results..."
    
    # Initialize score variables (like Tindroid)
    local confidentiality_score=0
    local integrity_score=0
    local availability_score=0
    local access_control_score=0
    
    # Collect results from individual test files
    local result_files=(
        "confidentiality_results.json"
        "integrity_results.json" 
        "availability_results.json"
        "access_control_results.json"
    )
    
    # Extract scores from each test result file
    for result_file in "${result_files[@]}"; do
        local file_path="$SCRIPT_DIR/$result_file"
        
        if [[ -f "$file_path" ]]; then
            local test_results
            test_results=$(cat "$file_path")
            
            # Extract the main score key (confidentiality, integrity, availability, access_control)
            local score_key
            score_key=$(echo "$test_results" | jq -r 'keys[] | select(. | test("^(confidentiality|integrity|availability|access_control)$"))' | head -1)
            
            if [[ -n "$score_key" && "$score_key" != "null" ]]; then
                local score
                score=$(echo "$test_results" | jq -r ".$score_key")
                
                if [[ "$score" != "null" && "$score" =~ ^[0-9]+\.?[0-9]*$ ]]; then
                    # Convert float scores to integer (1.0 -> 1)
                    local int_score
                    int_score=$(echo "$score" | cut -d. -f1)
                    
                    case "$score_key" in
                        "confidentiality")
                            confidentiality_score=$int_score
                            ;;
                        "integrity")
                            integrity_score=$int_score
                            ;;
                        "availability")
                            availability_score=$int_score
                            ;;
                        "access_control")
                            access_control_score=$int_score
                            ;;
                    esac
                fi
            fi
        else
            echo "Warning:" "Result file not found: $file_path"
        fi
    done
    
    # Create scores.json in the format expected by validation (like Tindroid)
    cat > "$RESULTS_FILE" <<EOF
{
  "scores": {
    "test_confidentiality": $confidentiality_score,
    "test_integrity": $integrity_score,
    "test_availability": $availability_score,
    "test_access_control": $access_control_score
  }
}
EOF
    
    echo "Results collected in $RESULTS_FILE"
    
    # Display summary
    echo
    echo "=" * 50
    echo "FINAL RESULTS SUMMARY"
    echo "=" * 50
    echo "Individual Scores:"
    echo "CONFIDENTIALITY: $confidentiality_score"
    echo "INTEGRITY: $integrity_score"
    echo "AVAILABILITY: $availability_score"
    echo "ACCESS_CONTROL: $access_control_score"
    echo "=" * 50
}

main() {
    echo "Starting SimpleLogin CIAA security tests..."
    
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
    echo "All tests completed. Collecting results..."
    
    collect_results
    
    echo "CIAA security tests completed!"
    echo "Passed: $passed_tests/$total_tests tests"
    echo "Results file: $RESULTS_FILE"
    
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
