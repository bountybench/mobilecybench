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
    {levels = {min = "info"}, to = "console"};
}

-- Certificates directory
certificates = "certs"

-- Virtual host for 10.0.2.2 (emulator accessible)
VirtualHost "10.0.2.2"