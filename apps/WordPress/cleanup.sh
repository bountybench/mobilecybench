SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null )"
source "${ROOT_DIR}/utils/common.sh"
source "${ROOT_DIR}/utils/docker.sh"

log_info "Stopping docker-compose stacks..."
docker_compose_down

log_info "Removing files: scores.json baseline.json secrets.json"
rm -f scores.json baseline.json secrets.json vuln_scenarios/vuln_scenario_0/fake_agent_log.log WordPress.apk || true

stop_script="${ROOT_DIR}/stop_emulator.sh"
log_info "Stopping emulator via ${stop_script}"
bash "${stop_script}"