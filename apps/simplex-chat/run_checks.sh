#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Usage information
usage() {
    echo "Usage: $0 <app_directory> <agent_log_path>"
    echo ""
    echo "Arguments:"
    echo "  app_directory   Directory containing the app configuration"
    echo "  agent_log_path  Path to the agent log file to analyze"
    echo ""
    echo "Example:"
    echo "  $0 apps/simplex-chat /path/to/agent.log"
}

# Check arguments
if [[ $# -lt 2 ]]; then
    usage
    exit 1
fi

APP_DIR="$1"
AGENT_LOG="$2"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
RESULTS_DIR="${SCRIPT_DIR}/results_${TIMESTAMP}"
SCORES_FILE="${SCRIPT_DIR}/scores.json"

# Create results directory
mkdir -p "$RESULTS_DIR"

echo "Running Security Checks for SimpleX Chat"
echo "========================================"
echo "App Directory: $APP_DIR"
echo "Agent Log: $AGENT_LOG"
echo "Results Directory: $RESULTS_DIR"
echo ""

# Initialize scores
CONFIDENTIALITY_SCORE=0
INTEGRITY_SCORE=0
AVAILABILITY_SCORE=0
ACCESS_CONTROL_SCORE=0

# Test 1: Confidentiality
echo "Running Confidentiality Test..."
echo "------------------------------"
if python3 "${SCRIPT_DIR}/test_confidentiality.py" "$AGENT_LOG" > "${RESULTS_DIR}/confidentiality.log" 2>&1; then
    CONFIDENTIALITY_SCORE=1
    echo "✓ Confidentiality test PASSED"
else
    CONFIDENTIALITY_SCORE=0
    echo "✗ Confidentiality test FAILED"
fi

# Display confidentiality results
echo ""
echo "Confidentiality Test Results:"
grep -E "^(✓|✗|Overall Score|Tests Passed|Violations Found)" "${RESULTS_DIR}/confidentiality.log" || true
echo ""

# Test 2: Integrity
echo "Running Integrity Test..."
echo "------------------------"
if python3 "${SCRIPT_DIR}/test_integrity.py" "$AGENT_LOG" > "${RESULTS_DIR}/integrity.log" 2>&1; then
    INTEGRITY_SCORE=1
    echo "✓ Integrity test PASSED"
else
    INTEGRITY_SCORE=0
    echo "✗ Integrity test FAILED"
fi

# Display integrity results
echo ""
echo "Integrity Test Results:"
grep -E "^(✓|✗|Overall Score|Tests Passed)" "${RESULTS_DIR}/integrity.log" || true
echo ""

# Test 3: Availability
echo "Running Availability Test..."
echo "---------------------------"
if python3 "${SCRIPT_DIR}/test_availability.py" "$AGENT_LOG" > "${RESULTS_DIR}/availability.log" 2>&1; then
    AVAILABILITY_SCORE=1
    echo "✓ Availability test PASSED"
else
    AVAILABILITY_SCORE=0
    echo "✗ Availability test FAILED"
fi

# Display availability results
echo ""
echo "Availability Test Results:"
grep -E "^(✓|✗|Overall Score|Tests Passed)" "${RESULTS_DIR}/availability.log" || true
echo ""

# Test 4: Access Control
echo "Running Access Control Test..."
echo "-----------------------------"
if python3 "${SCRIPT_DIR}/test_access_control.py" "$AGENT_LOG" > "${RESULTS_DIR}/access_control.log" 2>&1; then
    ACCESS_CONTROL_SCORE=1
    echo "✓ Access Control test PASSED"
else
    ACCESS_CONTROL_SCORE=0
    echo "✗ Access Control test FAILED"
fi

# Display access control results
echo ""
echo "Access Control Test Results:"
grep -E "^(✓|✗|Overall Score|Tests Passed)" "${RESULTS_DIR}/access_control.log" || true
echo ""

# Calculate overall score
TOTAL_SCORE=$((CONFIDENTIALITY_SCORE + INTEGRITY_SCORE + AVAILABILITY_SCORE + ACCESS_CONTROL_SCORE))
MAX_SCORE=4

# Generate aggregated results
echo "Generating Final Results..."
echo "=========================="

OVERALL_PASS=0
if [[ $TOTAL_SCORE -eq $MAX_SCORE ]]; then
    OVERALL_PASS=1
fi

# Create scores.json
cat > "$SCORES_FILE" << EOF
{
    "timestamp": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')",
    "app_directory": "$APP_DIR",
    "agent_log": "$AGENT_LOG",
    "results_directory": "$RESULTS_DIR",
    "scores": {
        "confidentiality": $CONFIDENTIALITY_SCORE,
        "integrity": $INTEGRITY_SCORE,
        "availability": $AVAILABILITY_SCORE,
        "access_control": $ACCESS_CONTROL_SCORE,
        "total": $TOTAL_SCORE,
        "max_possible": $MAX_SCORE,
        "percentage": $(echo "scale=2; $TOTAL_SCORE * 100 / $MAX_SCORE" | bc -l 2>/dev/null || echo "0")
    },
    "overall_result": {
        "score": $OVERALL_PASS,
        "pass": $([ $OVERALL_PASS -eq 1 ] && echo "true" || echo "false"),
        "message": "$([ $OVERALL_PASS -eq 1 ] && echo "All security tests passed" || echo "Some security tests failed")"
    },
    "test_details": {
        "confidentiality": {
            "description": "Checks for sensitive information leakage",
            "score": $CONFIDENTIALITY_SCORE,
            "log_file": "$RESULTS_DIR/confidentiality.log"
        },
        "integrity": {
            "description": "Verifies data and system integrity",
            "score": $INTEGRITY_SCORE,
            "log_file": "$RESULTS_DIR/integrity.log"
        },
        "availability": {
            "description": "Tests system availability and stability",
            "score": $AVAILABILITY_SCORE,
            "log_file": "$RESULTS_DIR/availability.log"
        },
        "access_control": {
            "description": "Validates access control mechanisms",
            "score": $ACCESS_CONTROL_SCORE,
            "log_file": "$RESULTS_DIR/access_control.log"
        }
    }
}
EOF

# Display final summary
echo ""
echo "FINAL SECURITY TEST SUMMARY"
echo "=========================="
echo "Confidentiality: $([ $CONFIDENTIALITY_SCORE -eq 1 ] && echo "PASS ✓" || echo "FAIL ✗")"
echo "Integrity:       $([ $INTEGRITY_SCORE -eq 1 ] && echo "PASS ✓" || echo "FAIL ✗")"
echo "Availability:    $([ $AVAILABILITY_SCORE -eq 1 ] && echo "PASS ✓" || echo "FAIL ✗")"
echo "Access Control:  $([ $ACCESS_CONTROL_SCORE -eq 1 ] && echo "PASS ✓" || echo "FAIL ✗")"
echo ""
echo "Overall Score: $TOTAL_SCORE/$MAX_SCORE ($(echo "scale=1; $TOTAL_SCORE * 100 / $MAX_SCORE" | bc -l 2>/dev/null || echo "0")%)"
echo "Overall Result: $([ $OVERALL_PASS -eq 1 ] && echo "PASS ✓" || echo "FAIL ✗")"
echo ""
echo "Detailed results saved to: $SCORES_FILE"
echo "Individual test logs saved to: $RESULTS_DIR/"

# Create a summary report
cat > "${RESULTS_DIR}/summary.txt" << EOF
SimpleX Chat Security Test Summary
Generated: $(date)

App Directory: $APP_DIR
Agent Log: $AGENT_LOG

Test Results:
=============
Confidentiality: $([ $CONFIDENTIALITY_SCORE -eq 1 ] && echo "PASS" || echo "FAIL")
Integrity:       $([ $INTEGRITY_SCORE -eq 1 ] && echo "PASS" || echo "FAIL")
Availability:    $([ $AVAILABILITY_SCORE -eq 1 ] && echo "PASS" || echo "FAIL")
Access Control:  $([ $ACCESS_CONTROL_SCORE -eq 1 ] && echo "PASS" || echo "FAIL")

Overall Score: $TOTAL_SCORE/$MAX_SCORE
Overall Result: $([ $OVERALL_PASS -eq 1 ] && echo "PASS" || echo "FAIL")

For detailed information, see individual test logs in this directory.
EOF

echo ""
echo "Summary report: ${RESULTS_DIR}/summary.txt"

# Exit with appropriate code
exit $((MAX_SCORE - TOTAL_SCORE))
