#!/usr/bin/env python3
"""
Test integrity of OpenVPN system and data consistency.
Verifies that certificates, configurations, and system state remain consistent.
"""

import subprocess
import json
import hashlib
import os
import sys


def test_certificate_integrity():
    """Test that certificates are valid and consistent"""
    print("Testing certificate integrity...")

    try:
        # Verify CA certificate
        result = subprocess.run(
            [
                "docker",
                "exec",
                "openvpn-server",
                "openssl",
                "x509",
                "-in",
                "/etc/openvpn/pki/ca.crt",
                "-text",
                "-noout",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print("✗ CA certificate is invalid")
            return False

        # Verify server certificate
        result = subprocess.run(
            [
                "docker",
                "exec",
                "openvpn-server",
                "openssl",
                "x509",
                "-in",
                "/etc/openvpn/pki/issued/server.crt",
                "-text",
                "-noout",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print("✗ Server certificate is invalid")
            return False

        # Verify client certificate
        result = subprocess.run(
            [
                "docker",
                "exec",
                "openvpn-server",
                "openssl",
                "x509",
                "-in",
                "/etc/openvpn/pki/issued/android-client.crt",
                "-text",
                "-noout",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print("✗ Client certificate is invalid")
            return False

        print("✓ All certificates are valid")
        return True

    except Exception as e:
        print(f"Certificate integrity test error: {e}")
        return False


def test_configuration_consistency():
    """Test that OpenVPN configuration is consistent"""
    print("Testing configuration consistency...")

    try:
        # Check server configuration exists
        result = subprocess.run(
            ["docker", "exec", "openvpn-server", "cat", "/etc/openvpn/openvpn.conf"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print("✗ Server configuration missing")
            return False

        config_content = result.stdout

        # Verify essential configuration parameters
        required_configs = [
            "proto udp",
            "port 1194",
            "ca ca.crt",
            "cert server.crt",
            "key server.key",
            "dh dh.pem",
        ]

        missing_configs = []
        for config in required_configs:
            if config not in config_content:
                missing_configs.append(config)

        if missing_configs:
            print(f"✗ Missing configuration parameters: {missing_configs}")
            return False

        print("✓ Server configuration is consistent")
        return True

    except Exception as e:
        print(f"Configuration consistency test error: {e}")
        return False


def test_client_config_integrity():
    """Test that client configurations are valid"""
    print("Testing client configuration integrity...")

    client_configs = [
        "client-configs/android-client.ovpn",
        "client-configs/test-user-1.ovpn",
        "client-configs/test-user-2.ovpn",
    ]

    for config_file in client_configs:
        if not os.path.exists(config_file):
            print(f"✗ Client config {config_file} missing")
            return False

        try:
            with open(config_file, "r") as f:
                content = f.read()

            # Check for required client configuration elements
            required_elements = [
                "client",
                "remote 10.0.2.2 1194",
                "proto udp",
                "<ca>",
                "<cert>",
                "<key>",
            ]

            for element in required_elements:
                if element not in content:
                    print(f"✗ Client config {config_file} missing {element}")
                    return False

        except Exception as e:
            print(f"Error reading client config {config_file}: {e}")
            return False

    print("✓ All client configurations are valid")
    return True


def test_pki_consistency():
    """Test PKI file consistency and relationships"""
    print("Testing PKI consistency...")

    try:
        # Check that all required PKI files exist
        pki_files = [
            "/etc/openvpn/pki/ca.crt",
            "/etc/openvpn/pki/private/ca.key",
            "/etc/openvpn/pki/issued/server.crt",
            "/etc/openvpn/pki/private/server.key",
            "/etc/openvpn/pki/dh.pem",
            "/etc/openvpn/pki/issued/android-client.crt",
            "/etc/openvpn/pki/private/android-client.key",
        ]

        for pki_file in pki_files:
            result = subprocess.run(
                ["docker", "exec", "openvpn-server", "test", "-f", pki_file],
                capture_output=True,
            )

            if result.returncode != 0:
                print(f"✗ PKI file missing: {pki_file}")
                return False

        # Verify certificate chain
        result = subprocess.run(
            [
                "docker",
                "exec",
                "openvpn-server",
                "openssl",
                "verify",
                "-CAfile",
                "/etc/openvpn/pki/ca.crt",
                "/etc/openvpn/pki/issued/server.crt",
            ],
            capture_output=True,
            text=True,
        )

        if "OK" not in result.stdout:
            print("✗ Server certificate chain verification failed")
            return False

        # Verify client certificate chain
        result = subprocess.run(
            [
                "docker",
                "exec",
                "openvpn-server",
                "openssl",
                "verify",
                "-CAfile",
                "/etc/openvpn/pki/ca.crt",
                "/etc/openvpn/pki/issued/android-client.crt",
            ],
            capture_output=True,
            text=True,
        )

        if "OK" not in result.stdout:
            print("✗ Client certificate chain verification failed")
            return False

        print("✓ PKI consistency verified")
        return True

    except Exception as e:
        print(f"PKI consistency test error: {e}")
        return False


def test_file_permissions():
    """Test that sensitive files have correct permissions"""
    print("Testing file permissions...")

    try:
        # Check private key permissions
        result = subprocess.run(
            [
                "docker",
                "exec",
                "openvpn-server",
                "ls",
                "-la",
                "/etc/openvpn/pki/private/",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print("✗ Could not check private key permissions")
            return False

        lines = result.stdout.split("\n")
        for line in lines:
            if ".key" in line and line.strip():
                permissions = line.split()[0]
                # Private keys should not be world-readable
                if len(permissions) >= 10 and permissions[7:10] != "---":
                    print(f"✗ Private key has incorrect permissions: {line}")
                    return False

        print("✓ File permissions are correct")
        return True

    except Exception as e:
        print(f"File permissions test error: {e}")
        return False


def test_system_state_consistency():
    """Test that system state is consistent and stable"""
    print("Testing system state consistency...")

    try:
        # Check that OpenVPN process is running
        result = subprocess.run(
            ["docker", "exec", "openvpn-server", "pgrep", "openvpn"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print("✗ OpenVPN process not running")
            return False

        # Check that configuration files haven't been corrupted
        result = subprocess.run(
            [
                "docker",
                "exec",
                "openvpn-server",
                "openvpn",
                "--config",
                "/etc/openvpn/openvpn.conf",
                "--test-crypto",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print("✗ OpenVPN configuration test failed")
            return False

        print("✓ System state is consistent")
        return True

    except Exception as e:
        print(f"System state test error: {e}")
        return False


def main():
    print("Starting OpenVPN Integrity Tests...")

    tests = [
        test_certificate_integrity,
        test_configuration_consistency,
        test_client_config_integrity,
        test_pki_consistency,
        test_file_permissions,
        test_system_state_consistency,
    ]

    passed_tests = 0
    total_tests = len(tests)

    for test in tests:
        try:
            if test():
                passed_tests += 1
        except Exception as e:
            print(f"Test failed with exception: {e}")

    print(f"\nIntegrity Tests: {passed_tests}/{total_tests} passed")

    # Exit with 0 if all tests passed, 1 otherwise
    sys.exit(0 if passed_tests == total_tests else 1)


if __name__ == "__main__":
    main()
