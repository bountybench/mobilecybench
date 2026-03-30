#!/bin/bash
set -e

echo "Cleaning up Wallabag testing environment..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Stop and remove Docker containers
echo "Stopping Docker containers..."
docker compose down -v 2>/dev/null || echo "No compose services to stop"

# Clean up generated files
echo "Cleaning up generated files..."
rm -f scores.json generic_scores.json 2>/dev/null || true

# Clean up web scraping artifacts
rm -f cookies.txt login.html home.html client_form.html client_created.html 2>/dev/null || true

# Clean up vulnerability test artifacts
find . -type f -name "fake_agent_log.log" -delete 2>/dev/null || true

echo "Wallabag environment cleanup completed!"
