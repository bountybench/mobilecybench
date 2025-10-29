#!/usr/bin/env bash
# run_checks.sh for AnkiDroid
# Executes all security test modules and aggregates results into scores.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESULTS_DIR="${RESULTS_DIR:-$SCRIPT_DIR/../../results/ankidroid}"
SCORES_FILE="${SCRIPT_DIR}/scores.json"
LOG_PREFIX="[run_checks]"

info(){ printf '%s %s\n' "$LOG_PREFIX" "$*" >&2; }
warn(){ printf '%s[warn] %s\n' "$LOG_PREFIX" "$*" >&2; }
fail(){ printf '%s[error] %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

# Create results directory
mkdir -p "$RESULTS_DIR"

# Ensure adb is ready
adb start-server >/dev/null 2>&1 || true
adb wait-for-device || true

info "Running security tests..."

# Run each test and capture output
run_test() {
    local test_name="$1"
    local test_file="${SCRIPT_DIR}/${test_name}.py"

    if [[ ! -f "$test_file" ]]; then
        warn "Test file not found: $test_file"
        return 1
    fi

    info "Running $test_name..."
    python3 "$test_file" --results "$RESULTS_DIR" | tee "$RESULTS_DIR/${test_name}.jsonl"
}

# Run all tests
run_test "test_confidentiality"
run_test "test_integrity"
run_test "test_availability"
run_test "test_access_control"

# Aggregate results into scores.json
info "Aggregating results..."
python3 - "$RESULTS_DIR" "$SCORES_FILE" <<'PYTHON'
import json
import sys
import glob
import os

results_dir = sys.argv[1]
scores = {}

# Read all test result files
for filepath in glob.glob(os.path.join(results_dir, "test_*.jsonl")):
    test_name = os.path.basename(filepath).replace(".jsonl", "")
    try:
        with open(filepath, 'r') as f:
            result = json.load(f)
            scores[test_name] = result
    except Exception as e:
        scores[test_name] = {
            "name": test_name,
            "pass": False,
            "score": 0,
            "reason": f"Failed to parse result: {e}"
        }

# Calculate overall pass/fail
overall_pass = all(test.get("pass", False) for test in scores.values())

# Create final scores object
final_scores = {
    "scores": scores,
    "overall_pass": overall_pass
}

# Write to scores.json in app directory (for CI) and results directory (for records)
scores_file_app = sys.argv[2]  # Pass from shell script
scores_file_results = os.path.join(results_dir, "scores.json")

with open(scores_file_app, 'w') as f:
    json.dump(final_scores, f, indent=2)

with open(scores_file_results, 'w') as f:
    json.dump(final_scores, f, indent=2)

# Print summary
print(json.dumps(final_scores, indent=2))
PYTHON

info "Test results saved to $SCORES_FILE and $RESULTS_DIR/scores.json"
