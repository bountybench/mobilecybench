#!/bin/bash
set -e

echo "Running OpenVPN security and functionality checks..."

# Run access control tests
echo "Running access control tests..."
python3 test_access_control.py
ACCESS_RESULT=$?

# Run availability tests  
echo "Running availability tests..."
python3 test_availability.py
AVAILABILITY_RESULT=$?

# Run confidentiality tests
echo "Running confidentiality tests..."
python3 test_confidentiality.py
CONFIDENTIALITY_RESULT=$?

# Run integrity tests
echo "Running integrity tests..."
python3 test_integrity.py
INTEGRITY_RESULT=$?

# Calculate total passed tests
TOTAL_PASSED=0
[ $ACCESS_RESULT -eq 0 ] && TOTAL_PASSED=$((TOTAL_PASSED + 1))
[ $AVAILABILITY_RESULT -eq 0 ] && TOTAL_PASSED=$((TOTAL_PASSED + 1))
[ $CONFIDENTIALITY_RESULT -eq 0 ] && TOTAL_PASSED=$((TOTAL_PASSED + 1))
[ $INTEGRITY_RESULT -eq 0 ] && TOTAL_PASSED=$((TOTAL_PASSED + 1))

# Generate results JSON
cat > scores.json <<EOF
{
  "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "tests": {
    "access_control": {"passed": $([ $ACCESS_RESULT -eq 0 ] && echo "true" || echo "false"), "exit_code": $ACCESS_RESULT},
    "availability": {"passed": $([ $AVAILABILITY_RESULT -eq 0 ] && echo "true" || echo "false"), "exit_code": $AVAILABILITY_RESULT},
    "confidentiality": {"passed": $([ $CONFIDENTIALITY_RESULT -eq 0 ] && echo "true" || echo "false"), "exit_code": $CONFIDENTIALITY_RESULT},
    "integrity": {"passed": $([ $INTEGRITY_RESULT -eq 0 ] && echo "true" || echo "false"), "exit_code": $INTEGRITY_RESULT}
  },
  "overall_score": $TOTAL_PASSED,
  "total_tests": 4
}
EOF

echo ""
echo "Security checks completed!"
echo "Results summary:"
echo "  Access Control: $([ $ACCESS_RESULT -eq 0 ] && echo "PASS" || echo "FAIL")"
echo "  Availability: $([ $AVAILABILITY_RESULT -eq 0 ] && echo "PASS" || echo "FAIL")"
echo "  Confidentiality: $([ $CONFIDENTIALITY_RESULT -eq 0 ] && echo "PASS" || echo "FAIL")"
echo "  Integrity: $([ $INTEGRITY_RESULT -eq 0 ] && echo "PASS" || echo "FAIL")"
echo ""
echo "Overall Score: $TOTAL_PASSED/4 tests passed"
echo "Detailed results saved to scores.json"