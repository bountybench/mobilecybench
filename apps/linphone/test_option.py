#!/usr/bin/env python3
"""
Fixed SIP OPTIONS test - includes all required headers
"""

import socket
import random

def generate_branch():
    """Generate a random branch parameter for Via header"""
    return f"z9hG4bK{random.randint(100000, 999999)}"

def generate_tag():
    """Generate a random tag for From header"""
    return str(random.randint(1000000, 9999999))

def test_sip_options():
    """Send a properly formatted SIP OPTIONS request"""
    
    host = 'localhost'
    port = 5060
    
    # Generate unique identifiers
    branch = generate_branch()
    from_tag = generate_tag()
    call_id = f"test-{random.randint(100000, 999999)}@{host}"
    
    # Properly formatted SIP OPTIONS message with ALL required headers
    message = (
        f"OPTIONS sip:{host} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {host}:{port};branch={branch};rport\r\n"
        f"Max-Forwards: 70\r\n"
        f"From: <sip:test@{host}>;tag={from_tag}\r\n"
        f"To: <sip:{host}>\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: 1 OPTIONS\r\n"
        f"Contact: <sip:test@{host}:{port}>\r\n"
        f"Accept: application/sdp\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )
    
    print("="*70)
    print(f"Testing SIP Server: {host}:{port}")
    print("="*70)
    print("\n📤 Sending SIP OPTIONS request:")
    print("-"*70)
    print(message)
    print("-"*70)
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)
    
    try:
        # Send the request
        print(f"\n→ Sending to {host}:{port} via UDP...")
        sock.sendto(message.encode('utf-8'), (host, port))
        
        print("→ Waiting for response (timeout: 5 seconds)...")
        
        # Receive response
        data, addr = sock.recvfrom(4096)
        
        print(f"\n✅ SUCCESS! Received response from {addr[0]}:{addr[1]}")
        print("="*70)
        print("📥 SIP Response:")
        print("="*70)
        response = data.decode('utf-8', errors='replace')
        print(response)
        print("="*70)
        
        # Parse status line
        lines = response.split('\r\n')
        if lines:
            status_line = lines[0]
            print(f"\n📊 Status: {status_line}")
            
            if "200 OK" in status_line:
                print("✅ Server responded with 200 OK - Everything is working!")
            elif "SIP/2.0" in status_line:
                print("✅ Valid SIP response received")
        
        return True
        
    except socket.timeout:
        print("\n❌ ERROR: No response received (timeout after 5 seconds)")
        print("\n🔍 Troubleshooting steps:")
        print("1. Verify Flexisip is running:")
        print("   docker ps | grep flexisip")
        print("\n2. Check Flexisip logs for errors:")
        print("   docker logs flexisip --tail 50")
        print("\n3. Verify the container can receive UDP packets:")
        print("   docker exec flexisip netstat -uln | grep 5060")
        print("\n4. Try from inside the container:")
        print("   docker exec -it flexisip bash")
        print("   apt-get update && apt-get install -y netcat")
        print("   echo 'OPTIONS sip:localhost SIP/2.0' | nc -u localhost 5060")
        return False
        
    except Exception as e:
        print(f"\n❌ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        sock.close()
        print("\n🔌 Socket closed")

if __name__ == "__main__":
    print("\n" + "🚀 "*35)
    print("SIP OPTIONS Test Script")
    print("🚀 "*35 + "\n")
    
    success = test_sip_options()
    
    print("\n" + "="*70)
    if success:
        print("✅ TEST PASSED - SIP server is responding correctly")
    else:
        print("❌ TEST FAILED - SIP server did not respond")
    print("="*70 + "\n")