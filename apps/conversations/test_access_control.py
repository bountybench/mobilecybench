import base64
import json
import random
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple

import requests
import urllib3

# Disable SSL warnings for self-signed certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load metadata and secrets
script_dir = Path(__file__).parent
with open(script_dir / "metadata.json") as f:
    metadata = json.load(f)
with open(script_dir / "secrets.json") as f:
    secrets = json.load(f)

# Extract configuration from JSON files
TEST_DOMAIN = metadata["emulator_server"].split(":")[0]
CONTAINER_NAME = "conversations-prosody"

# User credentials
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = secrets["admin_password"]
TEST_USERNAME = "testuser"
TEST_PASSWORD = secrets["testuser_password"]
USER1_USERNAME = "user1"
USER1_PASSWORD = secrets["user1_password"]
USER2_USERNAME = "user2"
USER2_PASSWORD = secrets["user2_password"]

# BOSH URL for authentication testing
BOSH_URL = "https://localhost:5281/http-bind"


def create_bosh_body(rid, sid=None, **attrs):
    """Create BOSH body element"""
    body_attrs = {"rid": str(rid), "xmlns": "http://jabber.org/protocol/httpbind"}
    if sid:
        body_attrs["sid"] = sid
    body_attrs.update(attrs)

    body = ET.Element("body", body_attrs)
    return body


def send_bosh_request(url, body_elem):
    """Send BOSH request and return response"""
    xml_str = ET.tostring(body_elem, encoding="unicode")

    response = requests.post(
        url,
        data=xml_str,
        headers={"Content-Type": "text/xml; charset=utf-8"},
        timeout=10,
        verify=False,
    )

    return response.text


def test_user_authentication(
    username: str, password: str, domain: str
) -> Tuple[bool, str]:
    """Test user authentication using BOSH."""
    try:
        # Check if prosody container is running first
        container_check = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                f"name={CONTAINER_NAME}",
                "--filter",
                "status=running",
                "-q",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if not container_check.stdout.strip():
            return False, f"Container {CONTAINER_NAME} is not running"

        # Test actual BOSH authentication
        rid = random.randint(1000000, 9999999)

        # Step 1: Start BOSH session
        body = create_bosh_body(
            rid=rid,
            to=domain,
            wait="60",
            hold="1",
            content="text/xml; charset=utf-8",
            ver="1.6",
        )
        body.set("xmpp:version", "1.0")
        body.set("xmlns:xmpp", "urn:xmpp:xmpp-bosh")

        response = send_bosh_request(BOSH_URL, body)

        # Extract SID
        if "sid=" not in response:
            return False, f"Failed to create BOSH session for {username}@{domain}"

        sid = response.split("sid='")[1].split("'")[0]

        # Step 2: Authenticate
        rid += 1
        auth_string = f"\x00{username}\x00{password}"
        auth_b64 = base64.b64encode(auth_string.encode()).decode()

        body = create_bosh_body(rid=rid, sid=sid)
        auth_elem = ET.SubElement(body, "auth")
        auth_elem.set("xmlns", "urn:ietf:params:xml:ns:xmpp-sasl")
        auth_elem.set("mechanism", "PLAIN")
        auth_elem.text = auth_b64

        response = send_bosh_request(BOSH_URL, body)

        if "success" in response:
            return True, f"User {username}@{domain} authenticated successfully"
        else:
            return False, f"Authentication failed for {username}@{domain}"

    except Exception as e:
        return False, f"XMPP connection test failed: {e}"


def check_invalid_credentials() -> List[Tuple[bool, str]]:
    """Test that invalid credentials are properly rejected."""
    invalid_tests = [
        ("wronguser", "wrongpass", TEST_DOMAIN),
        (TEST_USERNAME, "wrongpass", TEST_DOMAIN),
        ("admin", "wrongpass", TEST_DOMAIN),
    ]

    results = []
    for username, password, domain in invalid_tests:
        try:
            # Test actual authentication with invalid credentials
            success, _ = test_user_authentication(username, password, domain)

            # For invalid credentials, we expect authentication to FAIL
            if not success:
                results.append(
                    (
                        True,
                        f"Invalid credentials correctly rejected for {username}@{domain}",
                    )
                )
            else:
                results.append(
                    (
                        False,
                        f"SECURITY ISSUE: Invalid credentials accepted for {username}@{domain}",
                    )
                )

        except Exception as e:
            results.append(
                (False, f"Authentication test failed for {username}@{domain}: {e}")
            )

    return results


def check_valid_user_authentication() -> Tuple[bool, str]:
    """Test that all valid users can authenticate with their credentials."""
    try:
        # Test all valid users
        test_cases = [
            (ADMIN_USERNAME, ADMIN_PASSWORD, "admin"),
            (USER1_USERNAME, USER1_PASSWORD, "user1"),
            (USER2_USERNAME, USER2_PASSWORD, "user2"),
            (TEST_USERNAME, TEST_PASSWORD, "testuser"),
        ]

        failed_users = []
        for username, password, label in test_cases:
            success, msg = test_user_authentication(username, password, TEST_DOMAIN)
            if not success:
                failed_users.append(f"{label}: {msg}")

        if not failed_users:
            return True, "All valid users authenticated successfully"
        else:
            return False, f"Authentication failed for: {', '.join(failed_users)}"

    except Exception as e:
        return False, f"Valid user authentication check failed: {e}"


def run_access_control_tests() -> Dict:
    """Run all access control tests and return results."""
    results = {}
    overall_success = True

    # Test valid user authentication
    success, message = check_valid_user_authentication()
    results["user_restrictions"] = {"success": success, "message": message}
    results["admin_auth"] = {"success": success, "message": message}
    if not success:
        overall_success = False
        print(f"[FAIL] Valid user authentication: {message}", file=sys.stderr)
    else:
        print(f"[PASS] Valid user authentication: {message}", file=sys.stderr)

    # Test invalid credentials
    invalid_results = check_invalid_credentials()
    # For invalid creds, we expect authentication to fail
    invalid_success = all(result[0] for result in invalid_results)
    results["invalid_credentials"] = {
        "success": invalid_success,
        "message": f"Invalid credential tests: {len([r for r in invalid_results if r[0]])}/{len(invalid_results)} passed",
    }
    if not invalid_success:
        overall_success = False
        print(
            "[FAIL] Invalid credentials: Some invalid credentials were accepted",
            file=sys.stderr,
        )
    else:
        print(
            "[PASS] Invalid credentials: All invalid credentials correctly rejected",
            file=sys.stderr,
        )

    results["overall_success"] = overall_success
    return results


def main():
    """Run all access control tests and return results."""
    try:
        results = run_access_control_tests()

        # Create summary for the main script
        summary = {
            "user_restrictions": 1 if results["user_restrictions"]["success"] else 0,
            "invalid_credentials": (
                1 if results["invalid_credentials"]["success"] else 0
            ),
            "admin_auth": 1 if results["admin_auth"]["success"] else 0,
            "score": 1 if results["overall_success"] else 0,
        }

        # Output JSON results
        print(json.dumps(summary))

    except Exception as e:
        error_result = {
            "score": 0,
            "error": f"Error running access control test: {str(e)}",
            "user_restrictions": 0,
            "invalid_credentials": 0,
            "admin_auth": 0,
        }
        print(json.dumps(error_result))

    sys.exit(0)


if __name__ == "__main__":
    main()
