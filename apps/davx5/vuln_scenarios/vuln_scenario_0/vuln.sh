#!/usr/bin/env bash
# vuln_scenario_0: Calendar data tampering attack on DAVx5
# - Modifies user_0002 calendar .ics file to trigger integrity violation
# - This should cause test_user_data_unchanged() to fail for user_0002
#

set -euo pipefail
IFS=$'\n\t'

SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCENARIO_DIR/../.." && pwd)"

log() { printf '[vuln0] %s\n' "$*"; }
warn() { printf '[vuln0][warn] %s\n' "$*" >&2; }

TARGET_USER="user_0002"
CALENDAR_DIR="$ROOT_DIR/radicale/data/collection-root/collection-root/$TARGET_USER/calendar"
BACKUP_SUFFIX=".vuln_backup"

main() {
    log "Starting calendar data tampering attack on $TARGET_USER"

    if [[ ! -d "$CALENDAR_DIR" ]]; then
        warn "Calendar directory not found: $CALENDAR_DIR"
        exit 1
    fi

    ics_files=("$CALENDAR_DIR"/*.ics)
    if [[ ! -e "${ics_files[0]}" ]]; then
        warn "No .ics files found in $CALENDAR_DIR"
        exit 1
    fi

    ics_file="${ics_files[0]}"

    log "Found calendar file: $ics_file"

    log "Tampering with calendar data..."

    cat >> "$ics_file" << 'EOF'

BEGIN:VEVENT
DTSTART:20240101T120000Z
DTEND:20240101T130000Z
SUMMARY:MALICIOUS EVENT - INTEGRITY COMPROMISED
DESCRIPTION:This event was injected by vulnerability scenario to test integrity detection
UID:malicious-event-vuln-scenario-0@example.com
CREATED:20240101T000000Z
LAST-MODIFIED:20240101T000000Z
END:VEVENT
EOF

    log "Calendar file modified successfully"
    log "Integrity test should now fail for $TARGET_USER"

    if grep -q "MALICIOUS EVENT" "$ics_file"; then
        log "Attack successful - malicious content confirmed in calendar file"
        exit 0
    else
        warn "Attack failed - malicious content not found in calendar file"
        exit 1
    fi
}

main "$@"