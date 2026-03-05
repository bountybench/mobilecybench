#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

adb uninstall org.wordpress.android 2>/dev/null || true
docker compose down -v --remove-orphans 2>/dev/null || true
rm -f scores.json *.log
