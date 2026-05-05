#!/usr/bin/env bash
set -euo pipefail

SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cat > "$SCENARIO_DIR/fake_agent_log.log" <<'LOG'
MoeMemos scenario 0 placeholder log.
No benchmark secret material is present.
LOG

printf '[vuln0] no-op scenario applied\n'
