#!/bin/bash
set -euo pipefail

REPORT_FILE="submodule_size_report.txt"

format_size() {
    local size=$1
    if [[ "$size" -lt 1024 ]]; then
        printf "%dB" "$size"
    elif [[ "$size" -lt 1048576 ]]; then
        printf "%.2fKB" "$(awk "BEGIN {print $size/1024}")"
    elif [[ "$size" -lt 1073741824 ]]; then
        printf "%.2fMB" "$(awk "BEGIN {print $size/1048576}")"
    else
        printf "%.2fGB" "$(awk "BEGIN {print $size/1073741824}")"
    fi
}

main() {
    echo "Initializing and updating submodules..."
    if ! git submodule init || ! git submodule update --recursive --progress; then
        echo "Error: Failed to initialize/update submodules" >&2
        exit 1
    fi

    echo ""
    echo "Generating report..."

    local -a submodules
    while IFS= read -r line; do
        submodules+=("$line")
    done < <(git config --file .gitmodules --get-regexp path | awk '{print $2}')

    {
        printf "===========================================================\n"
        printf "App Codebase / Submodule Size Report - %s\n" "$(date '+%Y-%m-%d %H:%M:%S')"
        printf "===========================================================\n\n"
    } > "$REPORT_FILE"

    local total_size=0
    local count=0
    for submodule in "${submodules[@]}"; do
        [[ -d "$submodule" ]] || continue

        ((count++))
        echo "Analyzing: $submodule"

        local size file_count
        size=$(du -sk "$submodule" 2>/dev/null | cut -f1 || echo "0")
        local bytes=$((size * 1024))

        file_count=$(find "$submodule" -type f ! -path "*/.git/*" 2>/dev/null | wc -l | tr -d ' ')
        [[ -z "$file_count" ]] && file_count=0

        total_size=$((total_size + bytes))
        
        {
            printf "Submodule: %s\n" "$submodule"
            printf "  Size:  %s (%d bytes)\n" "$(format_size "$bytes")" "$bytes"
            printf "  Files: %s\n\n" "$file_count"
        } >> "$REPORT_FILE"
    done

    {
        printf "================================================\n"
        printf "Summary\n"
        printf "================================================\n"
        printf "Submodules/App Count: %d\n" "$count"
        printf "Total Size: %s (%d bytes)\n" "$(format_size "$total_size")" "$total_size"
        printf "================================================\n"
    } >> "$REPORT_FILE"

    echo ""
    echo "Done: $REPORT_FILE"
    echo "Total: $(format_size "$total_size") across $count submodules"
}

main "$@"
