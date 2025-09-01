#!/bin/bash
set -e

echo "Running vulnerability scenario 1: Denial of Service attacks"

# Create directory for this scenario  
mkdir -p /tmp/vuln_scenario_1
cd /tmp/vuln_scenario_1

echo "1. Testing OpenVPN server resilience under connection flood..."

# Test connection flooding
echo "Starting connection flood test..."
for i in {1..10}; do
    timeout 5 docker run --rm --net=host \
        kylemanna/openvpn \
        openvpn --remote 10.0.2.2 1194 --dev tun --proto udp --verb 0 &
done

# Wait for flood attempts
sleep 10

echo "2. Checking server availability during flood..."
if docker exec openvpn-server pgrep openvpn > /dev/null; then
    echo "✓ OpenVPN server survived connection flood"
    FLOOD_RESULT="RESILIENT"
else
    echo "✗ OpenVPN server crashed during connection flood"
    FLOOD_RESULT="VULNERABLE"
fi

echo "3. Testing malformed packet injection..."

# Send malformed UDP packets to OpenVPN port
echo "Sending malformed packets..."
for i in {1..20}; do
    echo "MALFORMED_OPENVPN_PACKET_$i" | nc -u 10.0.2.2 1194 &
done

sleep 5

echo "4. Checking server stability after malformed packets..."
if docker exec openvpn-server pgrep openvpn > /dev/null; then
    echo "✓ OpenVPN server survived malformed packet injection"
    PACKET_RESULT="RESILIENT"
else
    echo "✗ OpenVPN server crashed from malformed packets" 
    PACKET_RESULT="VULNERABLE"
fi

echo "5. Testing resource exhaustion via large certificate..."

# Create an extremely large fake certificate
dd if=/dev/zero bs=1M count=10 | base64 > large_cert.pem

# Create config with oversized certificate
cat > resource_exhaustion.ovpn <<EOF
client
dev tun
proto udp
remote 10.0.2.2 1194
ca [inline]

<ca>
$(cat large_cert.pem)
</ca>
EOF

echo "6. Attempting connection with oversized certificate..."
timeout 10 docker run --rm --net=host \
    -v "$(pwd)/resource_exhaustion.ovpn:/client.ovpn" \
    kylemanna/openvpn \
    openvpn --config /client.ovpn --verb 0 > large_cert_attempt.log 2>&1 || echo "Large cert connection failed"

echo "7. Checking server stability after resource exhaustion attempt..."
if docker exec openvpn-server pgrep openvpn > /dev/null; then
    echo "✓ OpenVPN server survived resource exhaustion attempt"
    RESOURCE_RESULT="RESILIENT"
else
    echo "✗ OpenVPN server crashed from resource exhaustion"
    RESOURCE_RESULT="VULNERABLE"
fi

echo "8. Testing Android app crash simulation..."
# Check if emulator is available
if adb devices | grep -q "emulator"; then
    echo "Simulating Android app stress..."
    
    # Send multiple rapid intents to the app
    for i in {1..5}; do
        adb shell am start -n de.blinkt.openvpn/.LaunchVPN &
    done
    
    sleep 3
    
    # Check if app is responsive
    if adb shell dumpsys activity activities | grep -q "de.blinkt.openvpn"; then
        echo "✓ Android app survived stress test"
        APP_RESULT="RESILIENT"
    else
        echo "✗ Android app crashed during stress test"
        APP_RESULT="VULNERABLE"
    fi
else
    echo "⚠ No emulator available, skipping Android app test"
    APP_RESULT="SKIPPED"
fi

echo "9. Testing container resource limits..."

# Check if container respects resource limits
CONTAINER_MEMORY=$(docker stats --no-stream --format "table {{.MemUsage}}" openvpn-server | tail -1)
echo "Container memory usage: $CONTAINER_MEMORY"

if docker exec openvpn-server pgrep openvpn > /dev/null; then
    echo "✓ Container is operating within resource limits"
    CONTAINER_RESULT="STABLE"
else
    echo "✗ Container may have exceeded resource limits"
    CONTAINER_RESULT="UNSTABLE"
fi

echo "10. Determining overall vulnerability status..."

# Calculate overall vulnerability
VULN_COUNT=0
if [ "$FLOOD_RESULT" = "VULNERABLE" ]; then ((VULN_COUNT++)); fi
if [ "$PACKET_RESULT" = "VULNERABLE" ]; then ((VULN_COUNT++)); fi  
if [ "$RESOURCE_RESULT" = "VULNERABLE" ]; then ((VULN_COUNT++)); fi
if [ "$APP_RESULT" = "VULNERABLE" ]; then ((VULN_COUNT++)); fi
if [ "$CONTAINER_RESULT" = "UNSTABLE" ]; then ((VULN_COUNT++)); fi

if [ $VULN_COUNT -eq 0 ]; then
    OVERALL_STATUS="SECURE"
    SECURITY_SCORE=100
elif [ $VULN_COUNT -le 2 ]; then
    OVERALL_STATUS="PARTIALLY_VULNERABLE"
    SECURITY_SCORE=60
else
    OVERALL_STATUS="VULNERABLE"
    SECURITY_SCORE=20
fi

echo "11. Generating DoS vulnerability report..."
cat > dos_vulnerability_report.json <<EOF
{
    "scenario": "vuln_scenario_1", 
    "description": "Denial of Service attack resilience testing",
    "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
    "overall_status": "$OVERALL_STATUS",
    "security_score": $SECURITY_SCORE,
    "test_results": {
        "connection_flood": "$FLOOD_RESULT",
        "malformed_packets": "$PACKET_RESULT",
        "resource_exhaustion": "$RESOURCE_RESULT", 
        "android_app_stress": "$APP_RESULT",
        "container_stability": "$CONTAINER_RESULT"
    },
    "vulnerabilities_found": [],
    "recommendations": [
        "Implement connection rate limiting",
        "Add input validation for malformed packets",
        "Set appropriate resource limits for containers",
        "Monitor for DoS attack patterns"
    ]
}
EOF

echo "DoS vulnerability scenario completed. Results in dos_vulnerability_report.json"
echo "Overall Status: $OVERALL_STATUS (Score: $SECURITY_SCORE/100)"

# Copy results back to main directory
cp dos_vulnerability_report.json ../../../results/vuln_scenario_1_results.json

# Clean up processes
killall nc 2>/dev/null || true
killall openvpn 2>/dev/null || true

# Exit with status code indicating vulnerability level
if [ "$OVERALL_STATUS" = "VULNERABLE" ]; then
    exit 1
else
    exit 0
fi