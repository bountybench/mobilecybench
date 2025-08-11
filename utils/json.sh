#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

json_init() {
    JSON_ITEMS=()
}

json_add_item() {
    if [[ $# -ne 1 ]]; then
        fatal "json_add_item expects 1 argument (json object string)"
    fi
    JSON_ITEMS+=("$1")
}

# Writes the JSON_ITEMS array to a file as a JSON credentials array.
json_write_file() {
    local out=${1:-secrets.json}
    local root_key=${2:-}
    if [[ -z "$root_key" ]]; then
        printf '%s\n' "${JSON_ITEMS[@]}" | jq -s '.' > "${out}"
    else
        printf '%s\n' "${JSON_ITEMS[@]}" | jq -s --arg key "$root_key" '{($key): .}' > "${out}"
    fi
    log_info "Wrote ${out} (${#JSON_ITEMS[@]} items)"
}
