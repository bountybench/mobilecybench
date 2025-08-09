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
    {
        echo '{'
        echo '  "credentials": ['
        local n=${#JSON_ITEMS[@]}
        for i in "${!JSON_ITEMS[@]}"; do
            if (( i < n-1 )); then
                printf '    %s,\n' "${JSON_ITEMS[i]}"
            else
                printf '    %s\n' "${JSON_ITEMS[i]}"
            fi
        done
        echo '  ]'
        echo '}'
    } > "${out}"
    log_info "Wrote ${out} (${#JSON_ITEMS[@]} items)"
}
