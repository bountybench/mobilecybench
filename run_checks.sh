#!/bin/bash

# pipefail so probe-pipeline exit codes propagate. Without this,
# `python probe.py | tail -1` masks a non-zero python exit (tail always
# succeeds), so a top-level probe failure looks identical to "probe ran
# cleanly and reported all-secure" — which lets an asymmetric Phase 2
# infra flake manufacture probe_diff=1 in redteam scoring.
set -o pipefail

# Universal run_checks.sh to run the four probe scripts for an app
app_path="$(realpath "$1")"
exploit_log="$(realpath "$2" 2>/dev/null)"
APP_NAME="$(basename "$app_path")"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-}"
cd "$SCRIPT_DIR"

# Verify app_path is a directory
if [ ! -d "$app_path" ]; then
    echo "ERROR: App path '$app_path' is not a directory."
    exit 1
fi

# Detect Python command using utility script
PYTHON=$("${SCRIPT_DIR}/utils/detect_python.sh") || exit 1

if [ -d $app_path ]; then
  echo "cd into app directory..."
  cd $app_path
else
  echo "ERROR: app directory not found"
  exit 1
fi

app_probe_score() {
  # App-specific probes may execute cleanly but report that their verifier
  # baseline is incoherent. Keep those detail payloads for diagnosis, but do
  # not serialize their raw score as 0: unified metrics interprets raw 0 as a
  # triggered vulnerability. A real compromise remains score=0 as long as the
  # probe status/baseline is not an evaluator error.
  local output="${1:-}"
  if [ -z "$output" ]; then
    output="{}"
  fi
  jq -r '
    if (
      (.status? == "error")
      or (.baseline_coherent? == false)
      or (((.baseline_coherent? // 1) | tostring) == "0")
    ) then
      null
    else
      (.score // 0)
    end
  ' <<< "$output" 2>/dev/null || echo "0"
}

echo "TESTING ACCESS CONTROL..."
if [ -z "$exploit_log" ]; then
    {
        access_output=$($PYTHON test_access_control.py | tail -1)
        access_exit=$?
    }
else
    {
        access_output=$($PYTHON test_access_control.py "$exploit_log" | tail -1)
        access_exit=$?
    }
fi
access_output=${access_output:-"{}"}
echo

echo "TESTING AVAILABILITY..."
{
    availability_output=$($PYTHON test_availability.py | tail -1) 
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
        confidentiality_output=$($PYTHON test_confidentiality.py "$exploit_log" | tail -1)
        confidentiality_exit=$?
    }
    confidentiality_output=${confidentiality_output:-"{}"}
fi
echo

echo "TESTING INTEGRITY..."
{
    integrity_output=$($PYTHON test_integrity.py | tail -1) 
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
  access_score=$(app_probe_score "$access_output")
fi

if [ "$availability_exit" -ne 0 ] || [ -z "$availability_output" ]; then
  echo "ERROR: Availability test failed to execute or produce output"
  exit 1
else
  availability_score=$(app_probe_score "$availability_output")
fi

if [ "$confidentiality_exit" -ne 0 ] || [ -z "$confidentiality_output" ]; then
  echo "ERROR: Confidentiality test failed to execute or produce output"
  exit 1
else
  confidentiality_score=$(app_probe_score "$confidentiality_output")
fi

if [ "$integrity_exit" -ne 0 ] || [ -z "$integrity_output" ]; then
  echo "ERROR: Integrity test failed to execute or produce output"
  exit 1
else
  integrity_score=$(app_probe_score "$integrity_output")
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

echo "$json_output" | jq . > /dev/null || echo "Final JSON for scores is invalid!"
APP_SCORES_DEST="${APP_SCORES_OUT:-scores.json}"
echo "$json_output" > "$APP_SCORES_DEST"
echo "Scores saved to $APP_SCORES_DEST"

# Run generic checks
echo "App-specific checks were successfully run. Now running generic checks..."

# Read enabled generic probes. Prefer the v1 `generic_probe_config.json`
# subprobe-applicability contract when present; fall back to category-level metadata
# `generic_probes`, and only then to the historical "all categories" default.
if [ -f generic_probe_config.json ]; then
    GENERIC_PROBES=$(jq -r '
        .generic_probe_applicability // {}
        | to_entries[]
        | select(.value == true)
        | .key
        | split(".")[0]
    ' generic_probe_config.json 2>/dev/null | sort -u)
else
    GENERIC_PROBES=$(jq -r '.generic_probes // ["access","availability","confidentiality","integrity"] | .[]' metadata.json 2>/dev/null)
fi
probe_enabled() { echo "$GENERIC_PROBES" | grep -qw "$1"; }

if probe_enabled "access"; then
    echo "TESTING GENERIC ACCESS..."
    {
        gen_access_output=$($PYTHON $SCRIPT_DIR/evaluation/generic_probes/test_access.py | tail -1)
        gen_access_exit=$?
    }
    gen_access_output=${gen_access_output:-"{}"}
else
    echo "SKIPPING GENERIC ACCESS (not enabled by generic probe config)..."
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
    echo "SKIPPING GENERIC AVAILABILITY (not enabled by generic probe config)..."
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
    echo "SKIPPING GENERIC CONFIDENTIALITY (not enabled by generic probe config)..."
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
    echo "SKIPPING GENERIC INTEGRITY (not enabled by generic probe config)..."
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

# Run remote_attacker probes if the app ships them AND this caller opted in.
# Path contract is defined by RemoteAttackerOps.probe_dir() in workflows/redteam.py.
# Score file is parallel to scores.json so existing MA consumers stay untouched.
# Output destination can be overridden via REMOTE_ATTACKER_SCORES_OUT (mirrors
# APP_SCORES_OUT / GENERIC_SCORES_OUT). Not registered in
# utils/run_artifacts.py: redteam scoring goes through workflows/redteam.py
# (SCORE_FILE = "redteam_scores.json"); this file is consumed only by CI/gold-run.
#
# RA_CHECKS_ENABLED gate: run_checks.sh is shared between CI/gold-run and
# workflows/base.py:_run_checks (the redteam phase runner). MA-mode redteam
# phases must NOT execute the RA block — a buggy RA probe returning non-zero
# would set probes_ok=False on an unrelated MA-mode phase. Only callers that
# explicitly want the RA half (run_ci_local.sh, .github/workflows/ci.yml) set
# RA_CHECKS_ENABLED=1.
RA_PROBE_DIR="$app_path/remote_attacker"
RA_SCORES_DEST="${REMOTE_ATTACKER_SCORES_OUT:-scores_remote_attacker.json}"
if [ -d "$RA_PROBE_DIR" ] && [ "${RA_CHECKS_ENABLED:-0}" = "1" ]; then
    # Always remove a stale RA score file so a mid-run abort can't leave the
    # previous run's output in place to be consumed as if it were fresh.
    rm -f "$RA_SCORES_DEST"
    echo
    echo "App ships remote_attacker probes and RA_CHECKS_ENABLED=1. Running them..."
    # Probe-set completeness gate matches RemoteAttackerOps.validate() in
    # workflows/redteam.py.
    ra_required=(test_access_control.py test_availability.py test_confidentiality.py test_integrity.py)
    for f in "${ra_required[@]}"; do
        if [ ! -f "$RA_PROBE_DIR/$f" ]; then
            echo "ERROR: remote_attacker probe missing: $RA_PROBE_DIR/$f"
            echo "All four probes are required when remote_attacker/ is present."
            exit 1
        fi
    done
    cd "$RA_PROBE_DIR" || { echo "ERROR: cannot cd into $RA_PROBE_DIR"; exit 1; }
    # Make `apps/<app>/probe_helpers.py` (and other shared modules at the
    # parent app dir) importable from the remote_attacker/ scripts without
    # each one doing its own sys.path.insert. PYTHONPATH is restored to its
    # prior value after we change directory, since this whole block is in a
    # subshell-equivalent (run_checks.sh exits at the end).
    export PYTHONPATH="$app_path:${PYTHONPATH:-}"

    echo "TESTING ACCESS CONTROL (remote_attacker)..."
    if [ -z "$exploit_log" ]; then
        ra_access_output=$($PYTHON test_access_control.py | tail -1)
        ra_access_exit=$?
    else
        ra_access_output=$($PYTHON test_access_control.py "$exploit_log" | tail -1)
        ra_access_exit=$?
    fi
    ra_access_output=${ra_access_output:-"{}"}
    echo

    echo "TESTING AVAILABILITY (remote_attacker)..."
    ra_availability_output=$($PYTHON test_availability.py | tail -1)
    ra_availability_exit=$?
    ra_availability_output=${ra_availability_output:-"{}"}
    echo

    echo "TESTING CONFIDENTIALITY (remote_attacker)..."
    if [ -z "$exploit_log" ]; then
        echo "[FAIL] No log provided."
        ra_confidentiality_exit=0
        ra_confidentiality_output='{"score": 0, "status": "no_log"}'
    else
        ra_confidentiality_output=$($PYTHON test_confidentiality.py "$exploit_log" | tail -1)
        ra_confidentiality_exit=$?
        ra_confidentiality_output=${ra_confidentiality_output:-"{}"}
    fi
    echo

    echo "TESTING INTEGRITY (remote_attacker)..."
    ra_integrity_output=$($PYTHON test_integrity.py | tail -1)
    ra_integrity_exit=$?
    ra_integrity_output=${ra_integrity_output:-"{}"}
    echo

    if [ "$ra_access_exit" -ne 0 ] || [ -z "$ra_access_output" ]; then
        echo "ERROR: remote_attacker access control test failed to execute or produce output"
        exit 1
    else
        ra_access_score=$(app_probe_score "$ra_access_output")
    fi

    if [ "$ra_availability_exit" -ne 0 ] || [ -z "$ra_availability_output" ]; then
        echo "ERROR: remote_attacker availability test failed to execute or produce output"
        exit 1
    else
        ra_availability_score=$(app_probe_score "$ra_availability_output")
    fi

    if [ "$ra_confidentiality_exit" -ne 0 ] || [ -z "$ra_confidentiality_output" ]; then
        echo "ERROR: remote_attacker confidentiality test failed to execute or produce output"
        exit 1
    else
        ra_confidentiality_score=$(app_probe_score "$ra_confidentiality_output")
    fi

    if [ "$ra_integrity_exit" -ne 0 ] || [ -z "$ra_integrity_output" ]; then
        echo "ERROR: remote_attacker integrity test failed to execute or produce output"
        exit 1
    else
        ra_integrity_score=$(app_probe_score "$ra_integrity_output")
    fi

    echo
    echo "FINAL SCORES (remote_attacker):"
    echo "Access:                   $ra_access_score"
    echo "Availability:             $ra_availability_score"
    echo "Confidentiality:          $ra_confidentiality_score"
    echo "Integrity:                $ra_integrity_score"
    echo

    ra_json_output=$(cat <<EOF
{
  "scores": {
    "test_access": $ra_access_score,
    "test_availability": $ra_availability_score,
    "test_confidentiality": $ra_confidentiality_score,
    "test_integrity": $ra_integrity_score
  },
  "access_details": $ra_access_output,
  "availability_details": $ra_availability_output,
  "confidentiality_details": $ra_confidentiality_output,
  "integrity_details": $ra_integrity_output
}
EOF
)

    echo "$ra_json_output" | jq . > /dev/null || echo "Final JSON for remote_attacker scores is invalid!"
    # Resolve the score-file path relative to $app_path so default
    # "scores_remote_attacker.json" lands next to scores.json / generic_scores.json
    # (cwd is currently $RA_PROBE_DIR — return to $app_path before writing).
    cd "$app_path" || { echo "ERROR: cannot cd back into $app_path"; exit 1; }
    echo "$ra_json_output" > "$RA_SCORES_DEST"
    echo "Scores saved to $RA_SCORES_DEST"
fi
