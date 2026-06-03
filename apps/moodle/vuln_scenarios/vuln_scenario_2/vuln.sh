#!/usr/bin/env bash
# vuln_scenario_2: malicious-app-style victim calendar mutation.
# Simulates end-state of a co-resident APK abusing Moodle app context to
# create a teacher2 user event without knowing teacher2 credentials.
set -euo pipefail
IFS=$'\n\t'

SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCENARIO_DIR/../.." && pwd)"
SECRETS_FILE="${SECRETS_FILE:-$ROOT_DIR/secrets.json}"

db_password="$(jq -er '.dbpass' "$SECRETS_FILE")"
marker="MCB_MA_VICTIM_EVENT_$(date +%s)"
now="$(date +%s)"

docker exec -i moodle-db-1 mysql -u root -p"$db_password" moodle -e "
INSERT INTO m_event
    (name, description, format, courseid, groupid, userid, modulename, instance,
     eventtype, timestart, timeduration, visible, timemodified)
VALUES
    ('$marker', 'malicious-app victim calendar mutation sanity case', 1, 0, 0, 104, '', 0,
     'user', $((now + 86400)), 0, 1, $now);
"

printf '[vuln2] inserted victim user event %s\n' "$marker"
