#!/usr/bin/env bash
set -euo pipefail

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Logging function
LOG() { printf "%s\n" "$*" >&2; }

########## Mosquitto configuration helper ##########

create_mosquitto_config() {
  local mosquitto_dir="$SCRIPT_DIR/mosquitto"
  local config_dir="$mosquitto_dir/config"
  local config_file="$config_dir/mosquitto.conf"
  
  LOG "Creating Mosquitto configuration..."
  
  # Create mosquitto directories if they don't exist
  mkdir -p "$config_dir"
  mkdir -p "$mosquitto_dir/data"
  mkdir -p "$mosquitto_dir/log"
  
  # Create mosquitto.conf file
  cat > "$config_file" << 'EOF'
# Mosquitto configuration file for OpenHAB integration

# Allow anonymous connections (set to false for production)
allow_anonymous true

# Persistence settings
persistence true
persistence_location /mosquitto/data/

# Logging
log_dest file /mosquitto/log/mosquitto.log
log_dest stdout
log_type error
log_type warning
log_type notice
log_type information

# Connection message settings
connection_messages true

# Listener configuration
listener 1883 0.0.0.0

# Security settings (for production, consider enabling authentication)
# password_file /mosquitto/config/passwd
# acl_file /mosquitto/config/acl

# Protocol version settings
max_keepalive 65535
max_packet_size 1024

# Client settings
max_inflight_messages 20
max_queued_messages 100

# WebSocket support (optional)
# listener 9001
# protocol websockets
EOF

  LOG "Mosquitto configuration created at $config_file"
  
  # Set appropriate permissions
  chmod 644 "$config_file" 2>/dev/null || true
  
  # Ensure directories have correct permissions for mosquitto container
  chmod 755 "$mosquitto_dir" "$config_dir" "$mosquitto_dir/data" "$mosquitto_dir/log" 2>/dev/null || true
}

# Main execution - if script is run directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  create_mosquitto_config
fi