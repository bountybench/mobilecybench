#!/bin/bash
set -e

echo "Cleaning up Wallabag testing environment..."

# Kill any running emulator processes
echo "Stopping Android emulator..."
# Kill emulators via adb first
adb devices | grep emulator | cut -f1 | while read emulator_id; do
    echo "Killing emulator: $emulator_id"
    adb -s "$emulator_id" emu kill 2>/dev/null || true
done
# Then kill any remaining emulator processes
adb emu kill 2>/dev/null || true
pkill -f "emulator.*wallabag" 2>/dev/null || true
pkill -f "qemu.*android" 2>/dev/null || true
pkill -f "emulator.*avd" 2>/dev/null || true

# Stop adb server
echo "Stopping ADB server..."
adb kill-server 2>/dev/null || true

# Stop and remove Docker containers
echo "Stopping Docker containers..."
docker-compose down -v 2>/dev/null || echo "No compose services to stop"
docker stop wallabag-db-1 2>/dev/null || echo "No wallabag-db-1 container to stop"
docker rm wallabag-db-1 2>/dev/null || echo "No wallabag-db-1 container to remove"

# Clean up generated files
echo "Cleaning up generated files..."
rm -f *.apk || true
rm -f scores.json || true
rm -f *.log || true
rm -f init-db.sql || true
rm -rf downloads/ || true
rm -rf logs/ || true
rm -rf output/ || true

# Clean up web scraping artifacts  
rm -f cookies.txt login.html home.html client_form.html client_created.html token_response.json 2>/dev/null || true

# Clean up vulnerability test artifacts
find . -type f -name "fake_agent_log.log" -delete
rm -rf /tmp/vuln_scenario_* || true

echo "Wallabag environment cleanup completed!"
