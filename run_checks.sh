#!/bin/bash

# Universal run_checks.sh to run the four probe scripts for an app
app_path="$(realpath "$1")"
exploit_log="$(realpath "$2" 2>/dev/null)"
APP_NAME="$(basename "$app_path")"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Verify app_path is a directory
if [ ! -d "$app_path" ]; then
    echo "ERROR: App path '$app_path' is not a directory."
    exit 1
fi

# Detect Python command using utility script
PYTHON=$("${SCRIPT_DIR}/utils/detect_python.sh") || exit 1

APP_MODULE_PREFIX=""
if [ -f "$app_path/__init__.py" ] && [[ "$app_path" == "$SCRIPT_DIR/apps/"* ]]; then
  APP_MODULE_PREFIX="apps.$APP_NAME"
fi

run_app_probe() {
  local probe_name="$1"
  shift || true

  if [ -n "$APP_MODULE_PREFIX" ]; then
    (
      cd "$SCRIPT_DIR"
      "$PYTHON" -m "$APP_MODULE_PREFIX.$probe_name" "$@"
    )
  else
    "$PYTHON" "${probe_name}.py" "$@"
  fi
}

if [ -d $app_path ]; then
  echo "cd into app directory..."
  cd $app_path
else
  echo "ERROR: app directory not found"
  exit 1
fi

echo "TESTING ACCESS CONTROL..."
if [ -z "$exploit_log" ]; then
    {
        access_output=$(run_app_probe test_access_control | tail -1)
        access_exit=$?
    }
else
    {
        access_output=$(run_app_probe test_access_control "$exploit_log" | tail -1)
        access_exit=$?
    }
fi
access_output=${access_output:-"{}"}
echo

echo "TESTING AVAILABILITY..."
{
    availability_output=$(run_app_probe test_availability | tail -1) 
    availability_exit=$?
}
availability_output=${availability_output:-"{}"}
echo

echo "TESTING CONFIDENTIALITY..."
if [ -z "$exploit_log" ]; then
    echo "[FAIL] No log provided."
    confidentiality_exit=0
    confidentiality_output='{"score": 0, "status": "no_log"}'
else
    {
        confidentiality_output=$(run_app_probe test_confidentiality "$exploit_log" | tail -1)
        confidentiality_exit=$?
    }
    confidentiality_output=${confidentiality_output:-"{}"}
fi
echo

echo "TESTING INTEGRITY..."
{
    integrity_output=$(run_app_probe test_integrity | tail -1) 
    integrity_exit=$?
}
integrity_output=${integrity_output:-"{}"}
echo

# Standardized exit code handling: exit 0 = test executed successfully, read score from JSON
# Probes should never crash - if they do, it's an evaluator failure
if [ "$access_exit" -ne 0 ] || [ -z "$access_output" ]; then
  echo "ERROR: Access control test failed to execute or produce output"
  exit 1
else
  access_score=$(echo "$access_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi

if [ "$availability_exit" -ne 0 ] || [ -z "$availability_output" ]; then
  echo "ERROR: Availability test failed to execute or produce output"
  exit 1
else
  availability_score=$(echo "$availability_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi

if [ "$confidentiality_exit" -ne 0 ] || [ -z "$confidentiality_output" ]; then
  echo "ERROR: Confidentiality test failed to execute or produce output"
  exit 1
else
  confidentiality_score=$(echo "$confidentiality_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi

if [ "$integrity_exit" -ne 0 ] || [ -z "$integrity_output" ]; then
  echo "ERROR: Integrity test failed to execute or produce output"
  exit 1
else
  integrity_score=$(echo "$integrity_output" | jq -r '.score // 0' 2>/dev/null || echo "0")
fi

echo
echo "FINAL SCORES:"
echo "Access:                   $access_score"
echo "Availability:             $availability_score"
echo "Confidentiality:          $confidentiality_score"
echo "Integrity:                $integrity_score"
echo

# Standardized JSON schema
json_output=$(cat <<EOF
{
  "scores": {
    "test_access": $access_score,
    "test_availability": $availability_score,
    "test_confidentiality": $confidentiality_score,
    "test_integrity": $integrity_score
  },
  "access_details": $access_output,
  "availability_details": $availability_output,
  "confidentiality_details": $confidentiality_output,
  "integrity_details": $integrity_output
}
EOF
)

# Run detectors (detect_*.py) if any exist in the probe directory
detector_json="{}"
for detect_script in detect_*.py; do
    [ -f "$detect_script" ] || continue
    detect_name="${detect_script%.py}"
    echo "RUNNING DETECTOR: $detect_name..."
    if [ -z "$exploit_log" ]; then
        detect_raw=$($PYTHON "$detect_script" 2>&1)
        detect_exit=$?
    else
        detect_raw=$($PYTHON "$detect_script" "$exploit_log" 2>&1)
        detect_exit=$?
    fi
    detect_output=$(echo "$detect_raw" | tail -1)
    if [ "$detect_exit" -ne 0 ] || [ -z "$detect_output" ]; then
        echo "  WARNING: $detect_name failed (exit=$detect_exit), skipping"
        detect_output='{"score": null, "status": "evaluator_error"}'
    fi
    # Validate JSON before merging
    if ! echo "$detect_output" | jq . > /dev/null 2>&1; then
        echo "  WARNING: $detect_name produced invalid JSON, skipping"
        detect_output='{"score": null, "status": "invalid_json"}'
    fi
    detect_score=$(echo "$detect_output" | jq -r '.score // "null"' 2>/dev/null)
    echo "  $detect_name: $detect_score"
    detector_json=$(echo "$detector_json" | jq --arg k "$detect_name" --argjson v "$detect_output" '. + {($k): $v}')
done

echo "$json_output" | jq . > /dev/null || echo "Final JSON for scores is invalid!"
APP_SCORES_DEST="${APP_SCORES_OUT:-scores.json}"
echo "$json_output" > "$APP_SCORES_DEST"
echo "Scores saved to $APP_SCORES_DEST"

# Write detector results to separate file (not merged into scores.json —
# scores.json has a fixed schema validated by CI)
if [ "$detector_json" != "{}" ]; then
    DETECTOR_SCORES_DEST="${DETECTOR_SCORES_OUT:-detector_scores.json}"
    echo "$detector_json" | jq . > "$DETECTOR_SCORES_DEST"
    echo "Detector scores saved to detector_scores.json"
fi

# Run generic checks
echo "App-specific checks were successfully run. Now running generic checks..."

# Read enabled generic probes from metadata, defaulting to all if no specification
GENERIC_PROBES=$(jq -r '.generic_probes // ["access","availability","confidentiality","integrity"] | .[]' metadata.json 2>/dev/null)
probe_enabled() { echo "$GENERIC_PROBES" | grep -qw "$1"; }

if probe_enabled "access"; then
    echo "TESTING GENERIC ACCESS..."
    {
        gen_access_output=$($PYTHON $SCRIPT_DIR/evaluation/generic_probes/test_access.py | tail -1)
        gen_access_exit=$?
    }
    gen_access_output=${gen_access_output:-"{}"}
else
    echo "SKIPPING GENERIC ACCESS (not in generic_probes)..."
    gen_access_exit=0
    gen_access_output='{"score": null, "status": "skipped"}'
fi
echo

if probe_enabled "availability"; then
    echo "TESTING GENERIC AVAILABILITY..."
    {
        gen_availability_output=$($PYTHON $SCRIPT_DIR/evaluation/generic_probes/test_availability.py | tail -1)
        gen_availability_exit=$?
    }
    gen_availability_output=${gen_availability_output:-"{}"}
else
    echo "SKIPPING GENERIC AVAILABILITY (not in generic_probes)..."
    gen_availability_exit=0
    gen_availability_output='{"score": null, "status": "skipped"}'
fi
echo

if probe_enabled "confidentiality"; then
    echo "TESTING GENERIC CONFIDENTIALITY..."
    if [ -z "$exploit_log" ]; then
        echo "[FAIL] No log provided."
        gen_confidentiality_exit=0
        gen_confidentiality_output='{"score": 0, "status": "no_log"}'
    else
        {
            gen_confidentiality_output=$($PYTHON $SCRIPT_DIR/evaluation/generic_probes/test_confidentiality.py "$exploit_log" | tail -1)
            gen_confidentiality_exit=$?
        }
        gen_confidentiality_output=${gen_confidentiality_output:-"{}"}
    fi
else
    echo "SKIPPING GENERIC CONFIDENTIALITY (not in generic_probes)..."
    gen_confidentiality_exit=0
    gen_confidentiality_output='{"score": null, "status": "skipped"}'
fi
echo

if probe_enabled "integrity"; then
    echo "TESTING GENERIC INTEGRITY..."
    {
        gen_integrity_output=$($PYTHON $SCRIPT_DIR/evaluation/generic_probes/test_integrity.py | tail -1)
        gen_integrity_exit=$?
    }
    gen_integrity_output=${gen_integrity_output:-"{}"}
else
    echo "SKIPPING GENERIC INTEGRITY (not in generic_probes)..."
    gen_integrity_exit=0
    gen_integrity_output='{"score": null, "status": "skipped"}'
fi
echo


if [ "$gen_access_exit" -ne 0 ] || [ -z "$gen_access_output" ]; then
  echo "ERROR: Access test failed to execute or produce output"
  exit 1
else
  gen_access_score=$(echo "$gen_access_output" | jq '.score' 2>/dev/null || echo "0")
fi

if [ "$gen_availability_exit" -ne 0 ] || [ -z "$gen_availability_output" ]; then
  echo "ERROR: Availability test failed to execute or produce output"
  exit 1
else
  gen_availability_score=$(echo "$gen_availability_output" | jq '.score' 2>/dev/null || echo "0")
fi

if [ "$gen_confidentiality_exit" -ne 0 ] || [ -z "$gen_confidentiality_output" ]; then
  echo "ERROR: Confidentiality test failed to execute or produce output"
  exit 1
else
  gen_confidentiality_score=$(echo "$gen_confidentiality_output" | jq '.score' 2>/dev/null || echo "0")
fi

if [ "$gen_integrity_exit" -ne 0 ] || [ -z "$gen_integrity_output" ]; then
  echo "ERROR: Integrity test failed to execute or produce output"
  exit 1
else
  gen_integrity_score=$(echo "$gen_integrity_output" | jq '.score' 2>/dev/null || echo "0")
fi

echo
echo "FINAL SCORES:"
echo "Access (Generic Probe):                   $gen_access_score"
echo "Availability (Generic Probe):             $gen_availability_score"
echo "Confidentiality (Generic Probe):          $gen_confidentiality_score"
echo "Integrity (Generic Probe):                $gen_integrity_score"
echo

gen_json_output=$(cat <<EOF
{
  "scores": {
    "test_access": $gen_access_score,
    "test_availability": $gen_availability_score,
    "test_confidentiality": $gen_confidentiality_score,
    "test_integrity": $gen_integrity_score
  },
  "access_details": $gen_access_output,
  "availability_details": $gen_availability_output,
  "confidentiality_details": $gen_confidentiality_output,
  "integrity_details": $gen_integrity_output
}
EOF
)

echo "$gen_json_output" | jq . > /dev/null || echo "Final JSON for generic scores is invalid!"
GENERIC_SCORES_DEST="${GENERIC_SCORES_OUT:-generic_scores.json}"
echo "$gen_json_output" > "$GENERIC_SCORES_DEST"
echo "Scores saved to $GENERIC_SCORES_DEST"
