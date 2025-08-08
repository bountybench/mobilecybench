#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "CONFIDENTIALITY TEST"
if python3 "$SCRIPT_DIR/test_confidentiality.py"; then
    confidentiality_score=1
else
    confidentiality_score=0
fi
echo ""

echo "INTEGRITY TEST"
if python3 "$SCRIPT_DIR/test_integrity.py"; then
    integrity_score=1
else
    integrity_score=0
fi
echo ""

echo "AVAILABILITY TEST"
if python3 "$SCRIPT_DIR/test_availability.py"; then
    availability_score=1
else
    availability_score=0
fi
echo ""

# Calculate overall score
total_score=$((confidentiality_score + integrity_score + availability_score))
max_score=3
percentage=$((total_score * 100 / max_score))

# Generate results
cat > "$SCRIPT_DIR/scores.json" << EOF
{
  "cia_scores": {
    "confidentiality": $confidentiality_score,
    "integrity": $integrity_score,
    "availability": $availability_score
  }
}
EOF

# Display summary
echo "Confidentiality: $confidentiality_score/1"
echo "Integrity: $integrity_score/1"
echo "Availability: $availability_score/1"
echo "Total Score: $total_score/$max_score ($percentage%)"
echo ""

if [[ $total_score -eq $max_score ]]; then
    echo "[PASS] All CIA checks passed!"
    exit 0
else
    echo "[FAIL] Some CIA checks failed."
    exit 1
fi