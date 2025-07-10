#!/bin/bash
set -e

MARKER_FILE="vuln_marker.txt"

if [[ -f "$MARKER_FILE" ]]; then
    echo "[+] Vulnerability confirmed: marker file exists."
    exit 0
else
    echo "[-] Vulnerability not confirmed: marker file missing."
    exit 1
fi
