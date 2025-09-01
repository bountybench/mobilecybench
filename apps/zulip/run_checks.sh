#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/utils.sh"

set +e

availability_score=0
integrity_score=0
confidentiality_score=0
access_score=0

echo "Running checks..."

python3 test_availability.py