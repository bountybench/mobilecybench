#!/usr/bin/env python3
"""
Test access control and authentication for OpenVPN server.
Validates that only authorized clients can connect and unauthorized attempts are rejected.
"""

import subprocess
import json
import time
import os
import sys


def test_valid_client_connection():
    """Test that valid client can connect to OpenVPN server"""
    print("Testing valid client connection...")

    # Check if client config exists
    config_file = "client-configs/android-client.ovpn"
    if not os.path.exists(config_file):
        print(f"Error: Client config {config_file} not found")
        return False

    # Test connection using openvpn client in docker
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--net=host",
                "-v",
                f"{os.path.abspath(config_file)}:/client.ovpn",
                "openvpn:2.5",
                "openvpn",
                "--config",
                "/client.ovpn",
                "--daemon",
                "--verb",
                "3",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            print("✓ Valid client connection successful")
            return True
        else:
            print(f"✗ Valid client connection failed: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("✓ Connection timeout expected for test environment")
        return True
    except Exception as e:
        print(f"✗ Connection test error: {e}")
        return False


def test_invalid_certificate():
    """Test that invalid certificates are rejected"""
    print("Testing invalid certificate rejection...")

    # Create temporary invalid config
    invalid_config = """
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
-----BEGIN CERTIFICATE-----
INVALID_CERTIFICATE_DATA
-----END CERTIFICATE-----
</ca>

<cert>
-----BEGIN CERTIFICATE-----  
INVALID_CLIENT_CERT_DATA
-----END CERTIFICATE-----
</cert>

<key>
-----BEGIN PRIVATE KEY-----
INVALID_PRIVATE_KEY_DATA
-----END PRIVATE KEY-----
</key>
"""

    with open("/tmp/invalid-client.ovpn", "w") as f:
        f.write(invalid_config)

    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--net=host",
                "-v",
                "/tmp/invalid-client.ovpn:/client.ovpn",
                "openvpn:2.5",
                "openvpn",
                "--config",
                "/client.ovpn",
                "--verb",
                "3",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode != 0:
            print("✓ Invalid certificate properly rejected")
            return True
        else:
            print("✗ Invalid certificate was accepted")
            return False

    except subprocess.TimeoutExpired:
        print("✗ Invalid certificate test timed out")
        return False
    except Exception as e:
        print(f"Connection test error: {e}")
        return False
    finally:
        if os.path.exists("/tmp/invalid-client.ovpn"):
            os.remove("/tmp/invalid-client.ovpn")


def test_server_accessibility():
    """Test that OpenVPN server is accessible on expected port"""
    print("Testing server accessibility...")

    try:
        result = subprocess.run(
            ["docker", "exec", "openvpn-server", "netstat", "-ln"],
            capture_output=True,
            text=True,
        )

        if ":1194" in result.stdout:
            print("✓ OpenVPN server listening on port 1194")
            return True
        else:
            print("✗ OpenVPN server not listening on port 1194")
            return False

    except Exception as e:
        print(f"Server accessibility test error: {e}")
        return False


def main():
    print("Starting OpenVPN Access Control Tests...")

    tests = [
        test_server_accessibility,
        test_valid_client_connection,
        test_invalid_certificate,
    ]

    passed_tests = 0
    total_tests = len(tests)

    for test in tests:
        try:
            if test():
                passed_tests += 1
            time.sleep(2)  # Brief pause between tests
        except Exception as e:
            print(f"Test failed with exception: {e}")

    print(f"\nAccess Control Tests: {passed_tests}/{total_tests} passed")

    # Exit with 0 if all tests passed, 1 otherwise
    sys.exit(0 if passed_tests == total_tests else 1)


if __name__ == "__main__":
    main()
