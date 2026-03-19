#!/bin/bash

# Tests CVE-2024-44080 GIF vulnerability
# Creates a server for attacker to send info to


start_server(){
    echo "Starting Attacker Server..."
    # Kill any existing instance first
    if [ -f /tmp/attacker_server.pid ]; then
        kill $(cat /tmp/attacker_server.pid) 2>/dev/null || true
        rm /tmp/attacker_server.pid
    fi
    PYTHONIOENCODING=utf-8 nohup python3 "$(dirname "$0")/exploit_files/attacker_server.py" > /tmp/attacker_server.log 2>&1 &
    echo $! > /tmp/attacker_server.pid
    echo "Attacker server started with PID $(cat /tmp/attacker_server.pid)"
}


start_server