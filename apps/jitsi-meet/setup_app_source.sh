#!/bin/bash
[ -n "$BASH_VERSION" ] || exec bash "$0" "$@"
set -e
chmod +x setup_app_apk.sh
bash setup_app_apk.sh