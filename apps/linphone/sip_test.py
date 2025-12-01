#!/usr/bin/env python3
"""
Pure Python SIP REGISTER test over TCP
Compatible with Windows, Linux, Docker
"""

import argparse
import hashlib
import random
import socket
import sys


# Generate a random hex string
def rand_hex(n=16):
    return ''.join(random.choice("abcdef0123456789") for _ in range(n))


# Build a SIP Digest response (supports MD5 and SHA-256)
def compute_digest(username, realm, password, nonce, uri, method="REGISTER",
                   algorithm="MD5", nc="00000001", qop="auth"):

    if algorithm.upper() == "SHA-256":
        H = lambda x: hashlib.sha256(x.encode()).hexdigest()
    else:
        H = lambda x: hashlib.md5(x.encode()).hexdigest()

    cnonce = rand_hex()

    ha1 = H(f"{username}:{realm}:{password}")
    ha2 = H(f"{method}:{uri}")
    response = H(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")

    return response, cnonce


def test_sip_register(username, password, domain, server, port, verbose):

    # Use local loopback for safety (works with Docker port mapping)
    public_ip = "127.0.0.1"

    # Build unique identifiers
    call_id = rand_hex(12)
    tag = rand_hex(8)
    branch = f"z9hG4bK{rand_hex(8)}"

    uri = f"sip:{domain}"
    from_uri = f"sip:{username}@{domain}"

    # ---------------------------------------------------------
    # 1) INITIAL REGISTER (no auth)
    # ---------------------------------------------------------

    local_port = random.randint(50000, 60000)

    request1 = (
        f"REGISTER {uri} SIP/2.0\r\n"
        f"Via: SIP/2.0/TCP {public_ip}:{local_port};branch={branch};rport\r\n"
        f"From: <{from_uri}>;tag={tag}\r\n"
        f"To: <{from_uri}>\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Max-Forwards: 70\r\n"
        f"Supported: outbound\r\n"
        f"Accept: application/sdp, text/plain\r\n"
        f"Contact: <sip:{username}@{public_ip}:{local_port};transport=tcp>\r\n"
        f"User-Agent: PythonSIPTest/1.0\r\n"
        f"Expires: 3600\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )

    if verbose:
        print("==== INITIAL REGISTER (NO AUTH) ====")
        print(request1)

    # Open TCP socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((server, port))
        sock.sendall(request1.encode())

        data = sock.recv(4096).decode(errors="ignore")
        sock.close()
    except Exception as e:
        print(f"Socket error: {e}")
        return False

    if verbose:
        print("---- RESPONSE ----")
        print(data)

    status = data.split("\r\n")[0]
    if "401" not in status:
        print("Error: Expected 401 Unauthorized")
        return False

    # Parse challenge
    realm = None
    nonce = None
    opaque = None
    algorithm = "SHA-256"

    for line in data.split("\r\n"):
        if "WWW-Authenticate" in line:
            if 'realm="' in line:
                realm = line.split('realm="')[1].split('"')[0]
            if 'nonce="' in line:
                nonce = line.split('nonce="')[1].split('"')[0]
            if 'opaque="' in line:
                opaque = line.split('opaque="')[1].split('"')[0]
            if "SHA-256" in line:
                algorithm = "SHA-256"

    # compute digest
    response_hash, cnonce = compute_digest(
        username, realm, password, nonce,
        uri, algorithm=algorithm
    )

    auth_header = (
        'Digest '
        f'username="{username}", '
        f'realm="{realm}", '
        f'nonce="{nonce}", '
        f'opaque="{opaque}", '
        f'uri="{uri}", '
        f'algorithm="SHA-256", '
        'qop=auth, '
        'nc=00000001, '
        f'cnonce="{cnonce}", '
        f'response="{response_hash}"'
    )


    branch2 = f"z9hG4bK{rand_hex(8)}"

    request2 = (
        f"REGISTER {uri} SIP/2.0\r\n"
        f"Via: SIP/2.0/TCP {public_ip}:{local_port};branch={branch2};rport\r\n"
        f"From: <{from_uri}>;tag={tag}\r\n"
        f"To: <{from_uri}>\r\n"
        f"Call-ID: {call_id}\r\n"
        f"CSeq: 2 REGISTER\r\n"
        f"Max-Forwards: 70\r\n"
        f"Supported: outbound\r\n"
        f"Accept: application/sdp, text/plain\r\n"
        f"Contact: <sip:{username}@{public_ip}:{local_port};transport=tcp>\r\n"
        f"Authorization: {auth_header}\r\n"
        f"User-Agent: PythonSIPTest/1.0\r\n"
        f"Expires: 3600\r\n"
        f"Content-Length: 0\r\n"
        f"\r\n"
    )

    if verbose:
        print("==== AUTHENTICATED REGISTER ====")
        print(request2)

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((server, port))
        sock.sendall(request2.encode())

        data2 = sock.recv(4096).decode(errors="ignore")
        sock.close()
    except Exception as e:
        print(f"Socket error: {e}")
        return False

    if verbose:
        print("---- RESPONSE ----")
        print(data2)

    if "200 Registration successful" in data2.split("\r\n")[0]:
        return True

    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TCP SIP REGISTER Tester for Flexisip")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--server", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5060)
    parser.add_argument("-v", "--verbose", action="store_true")

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
        print("SIP REGISTER SUCCESS")
        sys.exit(0)
    else:
        print("SIP REGISTER FAILED")
        sys.exit(1)
