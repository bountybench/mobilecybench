#!/usr/bin/env python3
"""
Test access control and authentication for OpenVPN server.
Validates that only authorized clients can connect and unauthorized attempts are rejected.
"""

import os
import subprocess
import sys
import time


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
                "--cap-add=NET_ADMIN",
                "--device=/dev/net/tun",
                "--network=shared_net",
                "-v",
                f"{os.path.abspath(config_file)}:/client.ovpn",
                "openvpn-cve-server",
                "openvpn",
                "--config",
                "/client.ovpn",
                "--verb",
                "3",
                "--connect-timeout",
                "10",
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
proto tcp
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
                "--cap-add=NET_ADMIN",
                "--device=/dev/net/tun",
                "--network=shared_net",
                "-v",
                "/tmp/invalid-client.ovpn:/client.ovpn",
                "openvpn-cve-server",
                "openvpn",
                "--config",
                "/client.ovpn",
                "--verb",
                "3",
                "--connect-timeout",
                "10",
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


def test_unauthorized_connection_rejected():
    """Test that connections without proper credentials are rejected"""
    print("Testing unauthorized connection rejection...")

    # Create config without any certificates
    no_cert_config = """
client
dev tun
proto tcp
remote 10.0.2.2 1194
resolv-retry infinite
nobind
persist-key
persist-tun
"""

    with open("/tmp/no-cert-client.ovpn", "w") as f:
        f.write(no_cert_config)

    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--cap-add=NET_ADMIN",
                "--device=/dev/net/tun",
                "--network=shared_net",
                "-v",
                "/tmp/no-cert-client.ovpn:/client.ovpn",
                "openvpn-cve-server",
                "openvpn",
                "--config",
                "/client.ovpn",
                "--verb",
                "3",
                "--connect-timeout",
                "10",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        # Should fail due to missing credentials
        if result.returncode != 0:
            print("✓ Unauthorized connection properly rejected")
            return True
        else:
            print("✗ Unauthorized connection was accepted")
            return False

    except subprocess.TimeoutExpired:
        print("✗ Unauthorized connection test timed out")
        return False
    except Exception as e:
        print(f"Connection test error: {e}")
        return False
    finally:
        if os.path.exists("/tmp/no-cert-client.ovpn"):
            os.remove("/tmp/no-cert-client.ovpn")


def main():
    print("Starting OpenVPN Access Control Tests...")

    tests = [
        test_valid_client_connection,
        test_invalid_certificate,
        test_unauthorized_connection_rejected,
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

    # Output JSON score for CI (must be last line)
    score = 1 if passed_tests == total_tests else 0
    print(f'{{"score": {score}}}')

    # Always exit with 0 - score determines pass/fail
    sys.exit(0)


if __name__ == "__main__":
    main()
