#!/bin/bash
# Build a runner_config.json for a GKE Job by layering env-var overrides onto
# the committed base config. Factored out of entrypoint-gke.sh so the override
# logic is unit-testable without booting DinD + the emulator
# (see tests/infra/gke/test_external_agent_jobs.py).
#
# Usage: build_runner_config.sh <config_src> <config_dst>
#
# Overrides are driven by env vars set on the Job (see job-template.yaml):
#   always:   MODEL, VULN_ID, EMULATOR_BACKEND, DRY_RUN, GOLD_RUN
#   optional: AGENT_IMAGE, AGENT_MODE, WORKFLOW, PROBE_ONLY, ATTACKER_MODEL,
#             NO_CODEBASE, AGENT_WALLCLOCK_SECONDS, BUILD_TYPE, NETWORK_MODE,
#             MAX_ITERATIONS, MULTI_EXPLOIT, REPLAY_EXPLOIT_DIR
# Optional fields are written only when their env var is non-empty, so an
# unset var leaves the base config's value untouched (backward compatible).
set -e

CONFIG_SRC="${1:?usage: build_runner_config.sh <config_src> <config_dst>}"
CONFIG_DST="${2:?usage: build_runner_config.sh <config_src> <config_dst>}"

if [ ! -f "$CONFIG_SRC" ]; then
    echo "ERROR: $CONFIG_SRC not found" >&2
    exit 1
fi

EMULATOR_BACKEND="${EMULATOR_BACKEND:-container}"

# Normalize boolean env vars to JSON-safe "true"/"false" for jq --argjson.
# (Portable lowercasing — works under bash 3.2 as well as the Linux image.)
normalize_bool() {
    case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
        true | 1) echo true ;;
        *) echo false ;;
    esac
}
DRY_RUN="$(normalize_bool "${DRY_RUN:-false}")"
GOLD_RUN="$(normalize_bool "${GOLD_RUN:-false}")"

# Optional booleans: normalize only when explicitly set. Empty string is the
# "unset" sentinel the jq filter below checks before overriding.
PROBE_ONLY_B=""
[ -n "${PROBE_ONLY:-}" ] && PROBE_ONLY_B="$(normalize_bool "$PROBE_ONLY")"
NO_CODEBASE_B=""
[ -n "${NO_CODEBASE:-}" ] && NO_CODEBASE_B="$(normalize_bool "$NO_CODEBASE")"
MULTI_EXPLOIT_B=""
[ -n "${MULTI_EXPLOIT:-}" ] && MULTI_EXPLOIT_B="$(normalize_bool "$MULTI_EXPLOIT")"

jq --arg model "${MODEL:-}" \
   --arg vuln "${VULN_ID:-}" \
   --arg em "$EMULATOR_BACKEND" \
   --arg build_type "${BUILD_TYPE:-}" \
   --arg agent_image "${AGENT_IMAGE:-}" \
   --arg agent_mode "${AGENT_MODE:-}" \
   --arg workflow "${WORKFLOW:-}" \
   --arg attacker "${ATTACKER_MODEL:-}" \
   --arg network_mode "${NETWORK_MODE:-}" \
   --arg probe_only "$PROBE_ONLY_B" \
   --arg no_codebase "$NO_CODEBASE_B" \
   --arg multi_exploit "$MULTI_EXPLOIT_B" \
   --arg replay_exploit_dir "${REPLAY_EXPLOIT_DIR:-}" \
   --arg wallclock "${AGENT_WALLCLOCK_SECONDS:-}" \
   --arg max_iterations "${MAX_ITERATIONS:-}" \
   --argjson dryrun "$DRY_RUN" \
   --argjson goldrun "$GOLD_RUN" \
   '.emulator_display = "headless"
    | .emulator_backend = $em
    | .dry_run = $dryrun
    | .gold_run = $goldrun
    | if $model != "" then .model = $model else . end
    | if $vuln != "" then .synthetic_vuln_id = $vuln else . end
    | if $build_type != "" then .build_type = $build_type else . end
    | if $agent_image != "" then .agent_image = $agent_image else . end
    | if $agent_mode != "" then .agent_mode = $agent_mode else . end
    | if $workflow != "" then .workflow = $workflow else . end
    | if $attacker != "" then .attacker_model = $attacker else . end
    | if $network_mode != "" then .network_mode = $network_mode else . end
    | if $no_codebase != "" then .no_codebase = ($no_codebase == "true") else . end
    | if $wallclock != "" then .agent_wallclock_seconds = ($wallclock | tonumber) else . end
    | if $max_iterations != "" then .max_iterations = ($max_iterations | tonumber) else . end
    | if $multi_exploit != "" then .multi_exploit = ($multi_exploit == "true") else . end
    | if $replay_exploit_dir != "" then .replay_exploit_dir = $replay_exploit_dir else . end
    | if $probe_only == "true" then
          .probe_only = true | .synthetic_vuln_id = null | .task = null
      elif $probe_only == "false" then
          .probe_only = false
      else . end' \
   "$CONFIG_SRC" > "$CONFIG_DST"
