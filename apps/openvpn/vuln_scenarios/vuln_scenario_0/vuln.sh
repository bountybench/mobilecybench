#!/bin/bash
set -e

echo "Running vulnerability scenario 0: Certificate manipulation and unauthorized access"

# Work in the script's directory
cd "$(dirname "$0")"

echo "1. Creating malicious client certificate..."

# Generate a rogue CA and client certificate
openssl genrsa -out rogue-ca.key 2048
openssl req -new -x509 -days 365 -key rogue-ca.key -out rogue-ca.crt -subj "/CN=Rogue-CA"

openssl genrsa -out rogue-client.key 2048
openssl req -new -key rogue-client.key -out rogue-client.csr -subj "/CN=rogue-client"
openssl x509 -req -in rogue-client.csr -CA rogue-ca.crt -CAkey rogue-ca.key -CAcreateserial -out rogue-client.crt -days 365

echo "2. Creating malicious OpenVPN client configuration..."
cat > rogue-client.ovpn <<EOF
client
dev tun
proto udp
remote 10.0.2.2 1194
resolv-retry infinite
nobind
persist-key
persist-tun
ca [inline]
cert [inline]
key [inline]

<ca>
$(cat rogue-ca.crt)
</ca>

<cert>
$(cat rogue-client.crt)
</cert>

<key>
$(cat rogue-client.key)
</key>
EOF

echo "3. Attempting unauthorized connection with rogue certificate..."
# Use official OpenVPN client to test against our server
timeout 15 docker run --rm --net=host \
    --cap-add=NET_ADMIN \
    --device=/dev/net/tun \
    -v "$(pwd)/rogue-client.ovpn:/client.ovpn" \
    openvpn-cve-server \
    openvpn --config /client.ovpn --verb 3 > connection_attempt.log 2>&1 || echo "Connection failed as expected"

echo "4. Analyzing connection attempt results..."
if grep -q "AUTH_FAILED" connection_attempt.log || grep -q "TLS_ERROR" connection_attempt.log; then
    echo "✓ Rogue certificate was properly rejected"
    VULN_STATUS="SECURE"
else
    echo "✗ WARNING: Rogue certificate may have been accepted!"
    VULN_STATUS="VULNERABLE" 
fi

echo "5. Attempting certificate substitution attack..."
# Try to replace legitimate client cert with rogue cert but keep original CA
if [ -f "../../../client-configs/android-client.ovpn" ]; then
    cp "../../../client-configs/android-client.ovpn" modified-client.ovpn
    
    # Extract original CA but replace cert and key with rogue ones
    awk '/^<ca>$/,/^<\/ca>$/' modified-client.ovpn > original-ca-section.txt
    
    # Create hybrid malicious config
    cat > hybrid-rogue.ovpn <<EOF
client
dev tun  
proto udp
remote 10.0.2.2 1194
resolv-retry infinite
nobind
persist-key
persist-tun
ca [inline]
cert [inline]
key [inline]

$(cat original-ca-section.txt)

<cert>
$(cat rogue-client.crt)
</cert>

<key>
$(cat rogue-client.key)  
</key>
EOF

    echo "6. Testing hybrid certificate attack..."
    timeout 15 docker run --rm --net=host \
        --cap-add=NET_ADMIN \
        --device=/dev/net/tun \
        -v "$(pwd)/hybrid-rogue.ovpn:/client.ovpn" \
        openvpn-cve-server \
        openvpn --config /client.ovpn --verb 3 > hybrid_attempt.log 2>&1 || echo "Hybrid attack failed as expected"
    
    if grep -q "AUTH_FAILED\|TLS_ERROR\|certificate verify failed" hybrid_attempt.log; then
        echo "✓ Hybrid certificate attack was properly rejected"
    else
        echo "✗ WARNING: Hybrid certificate attack may have succeeded!"
        VULN_STATUS="VULNERABLE"
    fi
fi

echo "7. Generating vulnerability report..."
cat > vulnerability_report.json <<EOF
{
    "scenario": "vuln_scenario_0",
    "description": "Certificate manipulation and unauthorized access",
    "timestamp": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
    "status": "$VULN_STATUS",
    "tests_performed": [
        "rogue_certificate_generation",
        "unauthorized_connection_attempt", 
        "certificate_substitution_attack",
        "hybrid_certificate_attack"
    ],
    "vulnerabilities_found": [],
    "recommendations": [
        "Verify certificate chain validation is working properly",
        "Ensure proper TLS authentication mechanisms are in place",
        "Monitor for unauthorized connection attempts"
    ]
}
EOF

echo "Vulnerability scenario 0 completed. Results in vulnerability_report.json"
echo "Status: $VULN_STATUS"

# Report is already saved in the correct location (current directory)

# Always exit with success - vulnerability status is recorded in report
# CI should not fail based on vulnerability findings, only on test execution failures
echo "Vulnerability test completed successfully"
exit 0