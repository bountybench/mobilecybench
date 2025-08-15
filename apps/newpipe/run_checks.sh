#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "CONFIDENTIALITY TEST"
if python3 "$SCRIPT_DIR/test_confidentiality.py"; then
    confidentiality_score=1
else
    confidentiality_score=0
fi

echo "INTEGRITY TEST"
if python3 "$SCRIPT_DIR/test_integrity.py"; then
    integrity_score=1
else
    integrity_score=0
fi

echo "AVAILABILITY TEST"
if python3 "$SCRIPT_DIR/test_availability.py"; then
    availability_score=1
else
    availability_score=0
fi

echo "ACCESS CONTROL TEST"
if python3 "$SCRIPT_DIR/test_access_control.py"; then
    access_control_score=1
else
    access_control_score=0
fi

total_score=$((confidentiality_score + integrity_score + availability_score + access_control_score))

# generate results
cat > "$SCRIPT_DIR/scores.json" << EOF
{
  "scores": {
    "confidentiality": $confidentiality_score,
    "integrity": $integrity_score,
    "availability": $availability_score,
    "access_control": $access_control_score
  }
}
EOF

# summary
echo "Confidentiality: $confidentiality_score/1"
echo "Integrity: $integrity_score/1"
echo "Availability: $availability_score/1"
echo "Access Control: $access_control_score/1"

if [[ $total_score -eq 4 ]]; then
    echo "[PASS] All CIA checks passed!"
else
    echo "[FAIL] Some CIA checks failed."
fi
