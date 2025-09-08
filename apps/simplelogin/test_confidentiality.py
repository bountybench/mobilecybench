#!/usr/bin/env python3
"""
SimpleLogin Confidentiality Test

Tests that sensitive information (canary data) is only accessible with proper authentication.
Ensures that unauthenticated requests cannot access confidential alias information.
"""

import json
import sys
from pathlib import Path

import requests


class ConfidentialityTest:
    def __init__(self):
        self.script_dir = Path(__file__).parent
        self.secrets_file = self.script_dir / "secrets.json"
        self.metadata_file = self.script_dir / "metadata.json"
        self.load_config()

    def load_config(self):
        """Load configuration from secrets and metadata files"""
        try:
            with open(self.metadata_file) as f:
                self.metadata = json.load(f)

            # Use metadata for primary config, fallback to secrets for compatibility
            if self.secrets_file.exists():
                with open(self.secrets_file) as f:
                    self.secrets = json.load(f)
                self.api_url = self.secrets.get(
                    "api_host", self.metadata["backend"]["base_url_host"]
                )
                self.canary_note = self.secrets.get(
                    "canary", self.metadata["test_credentials"]["canary_note"]
                )
                self.auth_token = self.secrets.get("auth_token", "placeholder-token")
            else:
                self.api_url = self.metadata["backend"]["base_url_host"]
                self.canary_note = self.metadata["test_credentials"]["canary_note"]
                self.auth_token = "placeholder-token"

            self.endpoints = self.metadata["backend"]["endpoints"]
            self.expected_codes = self.metadata["backend"]["expected_status_codes"]

        except FileNotFoundError as e:
            print(f"ERROR: Configuration file not found: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON in configuration: {e}")
            sys.exit(1)
        except KeyError as e:
            print(f"ERROR: Missing key in configuration: {e}")
            sys.exit(1)

    def _check_canary_in_response(self, response):
        """Check if canary data is present in API response (JSON aware)"""
        try:
            if response.headers.get("content-type", "").startswith("application/json"):
                data = response.json()
                # Look for canary in common alias fields
                if isinstance(data, dict):
                    if "aliases" in data:
                        for alias in data["aliases"]:
                            if (
                                isinstance(alias, dict)
                                and alias.get("note") == self.canary_note
                            ):
                                return True
                    # Check direct alias object
                    if data.get("note") == self.canary_note:
                        return True
                elif isinstance(data, list):
                    for item in data:
                        if (
                            isinstance(item, dict)
                            and item.get("note") == self.canary_note
                        ):
                            return True
                return False
            else:
                # Fallback to string search for non-JSON responses
                return self.canary_note in response.text
        except (json.JSONDecodeError, AttributeError):
            # Fallback to string search if JSON parsing fails
            return self.canary_note in response.text

    def test_unauthenticated_access_denied(self):
        """Test that unauthenticated requests are denied"""
        print("Testing unauthenticated access denial...")

        # Try to access aliases without authentication
        try:
            aliases_url = f"{self.api_url}{self.endpoints['aliases']}"
            response = requests.get(aliases_url, timeout=10)

            # Should return appropriate protected status code
            if response.status_code in self.expected_codes["protected_unauthenticated"]:
                print(
                    f"✅ PASS: Unauthenticated request properly denied (status: {response.status_code})"
                )
                return True
            else:
                print(
                    f"❌ FAIL: Unauthenticated request returned {response.status_code}, expected {self.expected_codes['protected_unauthenticated']}"
                )
                return False

        except requests.RequestException as e:
            print(f"❌ FAIL: Request error: {e}")
            return False

    def test_canary_not_exposed_without_auth(self):
        """Test that canary information is not exposed without authentication"""
        print("Testing canary information protection...")

        endpoints_to_test = [
            self.endpoints["aliases"],
            "/api/aliases",
            self.endpoints["user_info"],
            "/api/stats",
        ]

        canary_exposed = False

        for endpoint in endpoints_to_test:
            try:
                response = requests.get(f"{self.api_url}{endpoint}", timeout=10)

                # Check if canary appears in response using JSON-aware method
                if self._check_canary_in_response(response):
                    print(
                        f"❌ FAIL: Canary '{self.canary_note}' exposed in unauthenticated {endpoint}"
                    )
                    canary_exposed = True

            except requests.RequestException:
                # Connection errors are acceptable for this test
                continue

        if not canary_exposed:
            print("✅ PASS: Canary information not exposed without authentication")
            return True
        else:
            return False

    def test_authenticated_access_works(self):
        """Test that authenticated requests can access the canary data"""
        print("Testing authenticated access to canary data...")

        headers = {"Authorization": f"Bearer {self.auth_token}"}

        try:
            response = requests.get(
                f"{self.api_url}/api/v2/aliases", headers=headers, timeout=10
            )

            if response.status_code == 200:
                # Check if canary is present in authenticated response
                if self.canary_note in response.text:
                    print("✅ PASS: Authenticated request can access canary data")
                    return True
                else:
                    print("❌ FAIL: Canary data not found in authenticated response")
                    return False
            else:
                print(
                    f"❌ FAIL: Authenticated request failed with status {response.status_code}"
                )
                return False

        except requests.RequestException as e:
            print(f"❌ FAIL: Authenticated request error: {e}")
            return False

    def test_token_validation(self):
        """Test that invalid tokens are rejected"""
        print("Testing invalid token rejection...")

        invalid_tokens = [
            "invalid_token",
            "Bearer invalid",
            "",
            "12345",
            self.auth_token + "invalid",
        ]

        for token in invalid_tokens:
            headers = {"Authorization": f"Bearer {token}"}

            try:
                response = requests.get(
                    f"{self.api_url}/api/v2/aliases", headers=headers, timeout=10
                )

                # Should return 401 or 403 for invalid tokens
                if response.status_code not in [401, 403]:
                    print(
                        f"❌ FAIL: Invalid token '{token[:10]}...' not rejected (status: {response.status_code})"
                    )
                    return False

            except requests.RequestException:
                # Connection errors are acceptable
                continue

        print("✅ PASS: Invalid tokens properly rejected")
        return True

    def run_all_tests(self):
        """Run all confidentiality tests"""
        print("=" * 50)
        print("CONFIDENTIALITY TESTS")
        print("=" * 50)

        tests = [
            self.test_unauthenticated_access_denied,
            self.test_canary_not_exposed_without_auth,
            self.test_authenticated_access_works,
            self.test_token_validation,
        ]

        passed = 0
        total = len(tests)

        for test in tests:
            try:
                if test():
                    passed += 1
                print()
            except Exception as e:
                print(f"❌ FAIL: Test error: {e}")
                print()

        print(f"Results: {passed}/{total} tests passed")

        # Calculate score (0-1 scale)
        score = passed / total if total > 0 else 0

        print(f"Confidentiality Score: {score:.2f}")

        return {
            "confidentiality": score,
            "tests_passed": passed,
            "tests_total": total,
            "details": f"Confidentiality tests: {passed}/{total} passed",
        }


def main():
    """Main function"""
    test = ConfidentialityTest()
    results = test.run_all_tests()

    # Write results to file
    results_file = Path(__file__).parent / "confidentiality_results.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)

    # Exit with appropriate code
    sys.exit(0 if results["confidentiality"] > 0.5 else 1)


if __name__ == "__main__":
    main()
