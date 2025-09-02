#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"



echo "Tampering emails for Integrity testing..."
cd "$SCRIPT_DIR"

# Use the Python available on PATH
python3 tamper.py
echo "Tampering completed."