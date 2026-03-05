daemonize = false;

-- Admin users
admins = { "admin@10.0.2.2" }

-- Modules
modules_enabled = {
    "roster"; 
    "saslauth"; 
    "tls"; 
    "dialback"; 
    "disco";
    "carbons"; 
    "pep"; 
    "private"; 
    "blocklist"; 
    "vcard4"; 
    "vcard_legacy";
    "version"; 
    "uptime"; 
    "time"; 
    "ping"; 
    "register";
    "mam";
    "csi_simple";
    "http";
    "bosh";
    "websocket";
}

-- Allow registration for testing
allow_registration = true

-- TLS settings
c2s_require_encryption = true
s2s_require_encryption = true
s2s_secure_auth = false

-- Rate limits
limits = {
  c2s = {
    rate = "10kb/s";
  };
  s2sin = {
    rate = "30kb/s";
  };
}

-- PID file
pidfile = "/var/run/prosody/prosody.pid"

-- Authentication
authentication = "internal_hashed"

-- Archive settings
archive_expires_after = "1w"

-- Logging
log = {
    debug = "/var/log/prosody/debug.log";
    info = "/var/log/prosody/prosody.log";
    error = "/var/log/prosody/prosody.err";
    "*console";
}

-- Certificates directory
certificates = "/etc/prosody/certs"

-- HTTP configuration
http_ports = { 5280 }
https_ports = { 5281 }
https_certificate = "/etc/prosody/certs/10.0.2.2.crt"
https_key = "/etc/prosody/certs/10.0.2.2.key"

-- Virtual host for 10.0.2.2 (emulator accessible)
VirtualHost "10.0.2.2"

-- MUC (Multi-User Chat) component for group chats
Component "conference.10.0.2.2" "muc"
    modules_enabled = { "muc_mam" }
    muc_log_by_default = true
    muc_log_all_rooms = true
