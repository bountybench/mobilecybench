#!/bin/bash

# Tests CVE-2024-44080 GIF vulnerability
# Creates a server for attacker to send info to


start_server(){
    echo "Starting Attacker Server..."
    PYTHONIOENCODING=utf-8 nohup python3 "$(dirname "$0")/exploit_files/attacker_server.py" > /tmp/attacker_server.log 2>&1 &
}


start_server