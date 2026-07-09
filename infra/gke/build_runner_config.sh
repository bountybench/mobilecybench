#!/bin/bash
# Build a runner_config.json for a GKE Job by layering env-var overrides onto
# the committed base config. Factored out of entrypoint-gke.sh so the override
# logic is unit-testable without booting DinD + the emulator
# (see tests/infra/gke/test_external_agent_jobs.py).
#
# Usage: build_runner_config.sh <config_src> <config_dst>
#
# Overrides are driven by env vars set on the Job (see job-template.yaml):
#   always:   MODEL, EMULATOR_BACKEND, DRY_RUN, GOLD_RUN
#   optional: AGENT_IMAGE, AGENT_MODE, WORKFLOW, PROBE_ONLY, ATTACKER_MODEL,
#             NO_CODEBASE, AGENT_WALLCLOCK_SECONDS
# Optional fields are written only when their env var is non-empty, so an
# unset var leaves the base config's value untouched. synthetic_vuln_id is
# always cleared; GKE no longer accepts synthetic VULN_ID jobs.
#
# network_mode and apk_obfuscation are NOT taken from env: they are derived
# from the effective no_codebase so every GKE cell matches the batch grid's
# visibility coupling (the same 1:1 the batch config's matrix+exclude encodes):
#   source-visible (no_codebase=false) -> network_mode=permissive, apk_obfuscation=off
#   apk_only       (no_codebase=true)  -> network_mode=restricted, apk_obfuscation=on
# This keeps a full-ablation GKE sweep semantically identical to the batch grid,
# so the two run paths can't silently drift apart.
set -e

CONFIG_SRC="${1:?usage: build_runner_config.sh <config_src> <config_dst>}"
CONFIG_DST="${2:?usage: build_runner_config.sh <config_src> <config_dst>}"

if [ ! -f "$CONFIG_SRC" ]; then
    echo "ERROR: $CONFIG_SRC not found" >&2
    exit 1
fi

EMULATOR_BACKEND="${EMULATOR_BACKEND:-container}"

if [ -n "${VULN_ID:-}" ]; then
    echo "ERROR: VULN_ID is retired for GKE jobs; use redteam probe-only jobs without synthetic_vuln_id." >&2
    exit 1
fi

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

if [ "$PROBE_ONLY_B" = "true" ] && { [ "$DRY_RUN" = "true" ] || [ "$GOLD_RUN" = "true" ]; }; then
    echo "ERROR: PROBE_ONLY is incompatible with DRY_RUN/GOLD_RUN for GKE jobs." >&2
    exit 1
fi

jq --arg model "${MODEL:-}" \
   --arg em "$EMULATOR_BACKEND" \
   --arg agent_image "${AGENT_IMAGE:-}" \
   --arg agent_mode "${AGENT_MODE:-}" \
   --arg workflow "${WORKFLOW:-}" \
   --arg attacker "${ATTACKER_MODEL:-}" \
   --arg probe_only "$PROBE_ONLY_B" \
   --arg no_codebase "$NO_CODEBASE_B" \
   --arg wallclock "${AGENT_WALLCLOCK_SECONDS:-}" \
   --argjson dryrun "$DRY_RUN" \
   --argjson goldrun "$GOLD_RUN" \
   '.emulator_display = "headless"
    | .emulator_backend = $em
    | .dry_run = $dryrun
    | .gold_run = $goldrun
    | .synthetic_vuln_id = null
    | if $model != "" then .model = $model else . end
    | if $agent_image != "" then .agent_image = $agent_image else . end
    | if $agent_mode != "" then .agent_mode = $agent_mode else . end
    | if $workflow != "" then .workflow = $workflow else . end
    | if $attacker != "" then .attacker_model = $attacker else . end
    | if $no_codebase != "" then .no_codebase = ($no_codebase == "true") else . end
    | .network_mode = (if .no_codebase then "restricted" else "permissive" end)
    | .apk_obfuscation = (if .no_codebase then "on" else "off" end)
    | if $wallclock != "" then .agent_wallclock_seconds = ($wallclock | tonumber) else . end
    | if $probe_only == "true" then
          .probe_only = true | .synthetic_vuln_id = null | .task = null
      elif $probe_only == "false" then
          .probe_only = false
      else . end' \
   "$CONFIG_SRC" > "$CONFIG_DST"
