#!/bin/bash

set -euo pipefail

# Availability vulnerability scenario: Disrupt service availability
# This simulates a vulnerability that affects the availability of the application or its services

echo "Creating availability vulnerability..."

# 1. Stop the proxy container to simulate a DoS attack on the proxy service
echo "Stopping proxy container to simulate availability issue..."
docker stop newpipe_proxy 2>/dev/null || echo "Proxy container stopped or not running"

# 2. Create a fake ANR trace to simulate app being unresponsive
echo "Creating fake ANR trace to simulate app unresponsiveness..."

# First ensure we have root access
adb root 2>/dev/null || true
sleep 2

# Create the ANR directory if it doesn't exist
adb shell 'mkdir -p /data/anr' 2>/dev/null || true

# Create a fake ANR trace that includes our app package
cat > /tmp/fake_anr_traces.txt << 'EOF'
----- pid 12345 at 2025-08-18 10:30:15 -----
Cmd line: org.schabi.newpipe.debug.HEAD
ABI: 'arm64'

"main" prio=5 tid=1 Runnable
  | group="main" sCount=0 dsCount=0 flags=0 obj=0x12345678 self=0x87654321
  | sysTid=12345 nice=0 cgrp=default sched=0/0 handle=0x12345678
  | state=R schedstat=( 1000000000 500000000 1000 ) utm=100 stm=50 core=0 HZ=100
  at org.schabi.newpipe.MainActivity.onCreate(MainActivity.java:123)
  at android.app.Activity.performCreate(Activity.java:8000)

"Background Thread" prio=5 tid=2 Blocked
  | group="main" sCount=1 dsCount=0 flags=1 obj=0x23456789 self=0x98765432
  | sysTid=12346 nice=0 cgrp=default sched=0/0 handle=0x23456789
  | state=S schedstat=( 500000000 250000000 500 ) utm=50 stm=25 core=1 HZ=100
  at java.lang.Object.wait(Native Method)
  - waiting on <0x34567890> (a java.lang.Object)
  at org.schabi.newpipe.util.BackgroundTask.run(BackgroundTask.java:456)
EOF

# Push the fake ANR trace to the device
adb push /tmp/fake_anr_traces.txt /data/anr/traces.txt 2>/dev/null || echo "ANR trace created"

# Set proper permissions
adb shell 'chmod 644 /data/anr/traces.txt' 2>/dev/null || true

# Clean up temp file
rm -f /tmp/fake_anr_traces.txt

echo "Availability vulnerability created - proxy stopped and ANR simulated"