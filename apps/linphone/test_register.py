import socket
import sys

# REGISTER message
message = (
    "REGISTER sip:flexisip.local SIP/2.0\r\n"
    "Via: SIP/2.0/UDP 10.0.2.2:5060;branch=z9hG4bKtest123\r\n"
    "From: <sip:usera@flexisip.local>;tag=test456\r\n"
    "To: <sip:usera@flexisip.local>\r\n"
    "Call-ID: testcall@host\r\n"
    "CSeq: 1 REGISTER\r\n"
    "Contact: <sip:usera@192.168.1.100:5060>\r\n"
    "Expires: 3600\r\n"
    "Max-Forwards: 70\r\n"
    "User-Agent: TestAgent\r\n"
    "Content-Length: 0\r\n"
    "\r\n"
)

# Create UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(5)

try:
    # Send to localhost:5060
    print("Sending REGISTER to localhost:5060...")
    sock.sendto(message.encode(), ('localhost', 5060))
    
    # Wait for response
    print("Waiting for response...")
    data, addr = sock.recvfrom(4096)
    print(f"\nReceived response from {addr}:")
    print(data.decode())
    
except socket.timeout:
    print("ERROR: No response received (timeout)")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
finally:
    sock.close()