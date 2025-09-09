#!/bin/bash

exploit_log="$1"

echo "Running Termux security tests..."

# Check if required test files exist
required_tests=(
    "test_access_control.py"
    "test_availability.py"
    "test_confidentiality.py"
    "test_integrity.py"
)

for test in "${required_tests[@]}"; do
    if [ ! -f "$test" ]; then
        echo "Error: Required test file '$test' not found"
        exit 1
    fi
done

echo "All required test files found"

# Run the tests and capture exit codes
echo "Running access control tests..."
python3 test_access_control.py
access_exit=$?

echo "Running availability tests..."
python3 test_availability.py
availability_exit=$?

echo "Running confidentiality tests..."
python3 test_confidentiality.py
confidentiality_exit=$?

echo "Running integrity tests..."
python3 test_integrity.py
integrity_exit=$?

# Convert exit codes to scores (0 = pass = 1, 1 = fail = 0)
if [ "$access_exit" -eq 0 ]; then
    access_score=1
else
    access_score=0
fi

if [ "$availability_exit" -eq 0 ]; then
    availability_score=1
else
    availability_score=0
fi

if [ "$confidentiality_exit" -eq 0 ]; then
    confidentiality_score=1
else
    confidentiality_score=0
fi

if [ "$integrity_exit" -eq 0 ]; then
    integrity_score=1
else
    integrity_score=0
fi

# Generate scores.json
json_output=$(cat <<EOF
{
  "scores": {
    "test_confidentiality": $confidentiality_score,
    "test_integrity": $integrity_score,
    "test_availability": $availability_score,
    "test_access": $access_score
  }
}
EOF
)

echo "$json_output" > scores.json

echo ""
echo "Test Results Summary:"
echo "========================"
echo "Access Control: $access_score (exit: $access_exit)"
echo "Availability: $availability_score (exit: $access_exit)"
echo "Confidentiality: $confidentiality_score (exit: $confidentiality_exit)"
echo "Integrity: $integrity_score (exit: $integrity_exit)"
echo ""
echo "Detailed results saved to: scores.json"
echo ""
echo "Vulnerability Status:"
echo "CVE-2023-41900: Content Provider Permission Bypass"
if [ $confidentiality_score -eq 0 ]; then
    echo " VULNERABILITY DETECTED - Tests should fail"
else
    echo "VULNERABILITY NOT DETECTED - Tests passing (may need vuln.sh)"
fi
