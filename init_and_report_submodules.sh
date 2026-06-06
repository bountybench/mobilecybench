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
    # Optional: any positional args are treated as submodule paths to scope
    # the init/update + report to. With no args, handle all
    # submodules. With args (e.g. `apps/jitsi-meet/codebase`), only those
    # paths are touched — useful when one app's clone is broken or slow
    # and you only need a different app's codebase.
    local -a paths=("$@")

    # Default no-args path: skip zerodays (a separate private repo only
    # needed for redteam zero-day tasks). To init it, pass `zerodays`
    # explicitly or run `git submodule update --init zerodays`. The
    # "registered?" guard preserves prior behavior on .gitmodules without
    # zerodays (test fixtures, forks).
    local exclude_zerodays_default=false
    if (( ${#paths[@]} == 0 )) \
       && git config --file .gitmodules --get-regexp path 2>/dev/null \
              | awk '{print $2}' | grep -qx 'zerodays'; then
        while IFS= read -r p; do
            [[ -n "$p" && "$p" != "zerodays" ]] && paths+=("$p")
        done < <(git config --file .gitmodules --get-regexp path | awk '{print $2}')
        exclude_zerodays_default=true
    fi

    if $exclude_zerodays_default; then
        echo "Initializing and updating submodules (all except zerodays)..."
    elif (( ${#paths[@]} > 0 )); then
        echo "Initializing and updating submodules: ${paths[*]}"
    else
        echo "Initializing and updating submodules (all)..."
    fi
    # ${paths[@]+"${paths[@]}"} expands to nothing when the array is unset
    # (set -u-safe) and to all elements otherwise. Plain ${paths[@]}
    # would trip `set -u` under bash <4.4 with an empty array.
    if ! git submodule init ${paths[@]+"${paths[@]}"} \
       || ! git submodule update --recursive --progress ${paths[@]+"${paths[@]}"}; then
        echo "Error: Failed to initialize/update submodules" >&2
        exit 1
    fi

    echo ""
    echo "Generating report..."

    local -a submodules
    while IFS= read -r line; do
        submodules+=("$line")
    done < <(git config --file .gitmodules --get-regexp path | awk '{print $2}')

    # If paths were given, scope the size report to those (or descendants).
    # A path arg matches any submodule whose path starts with it, so
    # `apps/jitsi-meet` matches `apps/jitsi-meet/codebase`.
    if (( ${#paths[@]} > 0 )); then
        local -a filtered=()
        for sm in "${submodules[@]}"; do
            for p in "${paths[@]}"; do
                # Strip trailing slashes for prefix matching.
                p="${p%/}"
                if [[ "$sm" == "$p" || "$sm" == "$p/"* ]]; then
                    filtered+=("$sm")
                    break
                fi
            done
        done
        submodules=("${filtered[@]}")
    fi

    {
        printf "===========================================================\n"
        printf "App Codebase / Submodule Size Report - %s\n" "$(date '+%Y-%m-%d %H:%M:%S')"
        printf "===========================================================\n\n"
    } > "$REPORT_FILE"

    local total_size=0
    local count=0
    for submodule in "${submodules[@]}"; do
        [[ -d "$submodule" ]] || continue

        count=$((count + 1))
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

    if $exclude_zerodays_default; then
        echo "Note: zerodays/ excluded (not required for probe_only mode). To init it: git submodule update --init zerodays"
    fi
}

main "$@"
