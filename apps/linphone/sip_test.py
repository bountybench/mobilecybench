#!/usr/bin/env python3
"""
Pure Python SIP REGISTER test - Works on Windows and Linux
No dependencies needed - uses only Python standard library
"""

import argparse
import hashlib
import random
import socket
import sys


def test_sip_register(
    username, password, domain, server="localhost", port=5060, verbose=False
):
    """
    Test SIP REGISTER authentication using pure Python.

    Args:
        username: SIP username (without @domain)
        password: User password
        domain: SIP domain (e.g., "sip.example.org")
        server: Flexisip server hostname/IP (default: "localhost")
        port: SIP port (default: 5060)
        verbose: Print detailed output (default: False)

    Returns:
        bool: True if authentication successful, False otherwise
    """

    # Get local IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except socket.timeout:
        local_ip = "127.0.0.1"

    # Generate unique identifiers
    call_id = f"{random.randint(1000000, 9999999)}@{local_ip}"
    tag = str(random.randint(1000000, 9999999))
    branch = f"z9hG4bK{random.randint(1000000, 9999999)}"

    if verbose:
        print(f"Testing: {username}@{domain}")
        print(f"Server: {server}:{port}")
        print("-" * 60)

    # Step 1: Send initial REGISTER (no auth)
    uri = f"sip:{domain}"
    from_uri = f"sip:{username}@{domain}"

    request1 = (
        f"REGISTER {uri} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {local_ip}:5060;branch={branch};rport\r\n"
        f"From: <{from_uri}>;tag={tag}\r\n"
        f"To: <{from_uri}>\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{username}@{local_ip}:5060>\r\n"
        f"Max-Forwards: 70\r\n"
        f"User-Agent: PythonSIPTest/1.0\r\n"
        f"Expires: 3600\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )

    if verbose:
        print("Sending initial REGISTER...")
        print(request1)

    # Send first request
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5.0)
        local_port = random.randint(5060, 65535)
        sock.bind((local_ip, local_port))
        sock.sendto(request1.encode(), (server, port))

        # Receive response
        data, _ = sock.recvfrom(4096)
        response1 = data.decode("utf-8", errors="ignore")
        sock.close()

    except socket.timeout:
        if verbose:
            print("ERROR: Timeout waiting for response")
        return False
    except Exception as e:
        if verbose:
            print(f"ERROR: {e}")
        return False

    if verbose:
        print("Received response:")
        print(response1)
        print("-" * 60)

    # Check for 401
    if "401" not in response1.split("\r\n")[0]:
        if verbose:
            print("ERROR: Expected 401 Unauthorized")
        return False

    # Step 2: Parse authentication challenge
    realm = None
    nonce = None

    for line in response1.split("\r\n"):
        if "WWW-Authenticate:" in line or "Proxy-Authenticate:" in line:
            if 'realm="' in line:
                start = line.index('realm="') + 7
                end = line.index('"', start)
                realm = line[start:end]

            if 'nonce="' in line:
                start = line.index('nonce="') + 7
                end = line.index('"', start)
                nonce = line[start:end]

    if not realm or not nonce:
        if verbose:
            print("ERROR: Could not parse authentication challenge")
        return False

    if verbose:
        print(f"Realm: {realm}")
        print(f"Nonce: {nonce}")
        print("-" * 60)

    # Step 3: Calculate MD5 response
    ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()
    ha2 = hashlib.md5(f"REGISTER:{uri}".encode()).hexdigest()
    response_hash = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()

    # Step 4: Send authenticated REGISTER
    branch2 = f"z9hG4bK{random.randint(1000000, 9999999)}"

    auth_header = (
        f'Digest username="{username}", '
        f'realm="{realm}", '
        f'nonce="{nonce}", '
        f'uri="{uri}", '
        f'response="{response_hash}", '
        f"algorithm=MD5"
    )

    request2 = (
        f"REGISTER {uri} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {local_ip}:5060;branch={branch2};rport\r\n"
        f"From: <{from_uri}>;tag={tag}\r\n"
        f"To: <{from_uri}>\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: 2 REGISTER\r\n"
        f"Contact: <sip:{username}@{local_ip}:5060>\r\n"
        f"Authorization: {auth_header}\r\n"
        f"Max-Forwards: 70\r\n"
        f"User-Agent: PythonSIPTest/1.0\r\n"
        f"Expires: 3600\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )

    if verbose:
        print("Sending authenticated REGISTER...")
        print(request2)

    # Send authenticated request
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5.0)
        local_port = random.randint(5060, 65535)
        sock.bind((local_ip, local_port))
        sock.sendto(request2.encode(), (server, port))

        # Receive response
        data, _ = sock.recvfrom(4096)
        response2 = data.decode("utf-8", errors="ignore")
        sock.close()

    except socket.timeout:
        if verbose:
            print("ERROR: Timeout waiting for response")
        return False
    except Exception as e:
        if verbose:
            print(f"ERROR: {e}")
        return False

    if verbose:
        print("Received response:")
        print(response2)
        print("-" * 60)

    # Check result
    status_line = response2.split("\r\n")[0]

    if "200 OK" in status_line:
        return True
    else:
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test SIP REGISTER authentication (Pure Python - Works on Windows/Linux)"
    )
    parser.add_argument("--username", required=True, help="SIP username")
    parser.add_argument("--password", required=True, help="User password")
    parser.add_argument("--domain", required=True, help="SIP domain")
    parser.add_argument(
        "--server", default="localhost", help="Flexisip server (default: localhost)"
    )
    parser.add_argument(
        "--port", type=int, default=5060, help="SIP port (default: 5060)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    success = test_sip_register(
        username=args.username,
        password=args.password,
        domain=args.domain,
        server=args.server,
        port=args.port,
        verbose=args.verbose,
    )

    if success:
        print("✓ Authentication successful")
        sys.exit(0)
    else:
        print("✗ Authentication failed")
        sys.exit(1)
