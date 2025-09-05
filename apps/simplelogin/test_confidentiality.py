#!/usr/bin/env python3
"""
SimpleLogin Confidentiality Test

Tests that sensitive information (canary data) is only accessible with proper authentication.
Ensures that unauthenticated requests cannot access confidential alias information.
"""

import json
import requests
import sys
from pathlib import Path


class ConfidentialityTest:
    def __init__(self):
        self.script_dir = Path(__file__).parent
        self.secrets_file = self.script_dir / "secrets.json"
        self.metadata_file = self.script_dir / "metadata.json"
        self.load_config()
    
    def load_config(self):
        """Load configuration from secrets and metadata files"""
        try:
            with open(self.secrets_file) as f:
                self.secrets = json.load(f)
            
            with open(self.metadata_file) as f:
                self.metadata = json.load(f)
                
            self.api_url = self.secrets["api_host"]
            self.canary_note = self.secrets["canary"]
            self.auth_token = self.secrets["auth_token"]
            
        except FileNotFoundError as e:
            print(f"ERROR: Configuration file not found: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON in configuration: {e}")
            sys.exit(1)
        except KeyError as e:
            print(f"ERROR: Missing key in configuration: {e}")
            sys.exit(1)
    
    def test_unauthenticated_access_denied(self):
        """Test that unauthenticated requests are denied"""
        print("Testing unauthenticated access denial...")
        
        # Try to access aliases without authentication
        try:
            response = requests.get(
                f"{self.api_url}/api/v2/aliases",
                timeout=10
            )
            
            # Should return 401 or 403
            if response.status_code in [401, 403]:
                print("✅ PASS: Unauthenticated request properly denied")
                return True
            else:
                print(f"❌ FAIL: Unauthenticated request returned {response.status_code}, expected 401/403")
                return False
                
        except requests.RequestException as e:
            print(f"❌ FAIL: Request error: {e}")
            return False
    
    def test_canary_not_exposed_without_auth(self):
        """Test that canary information is not exposed without authentication"""
        print("Testing canary information protection...")
        
        endpoints_to_test = [
            "/api/v2/aliases",
            "/api/aliases",
            "/api/user/info",
            "/api/stats",
        ]
        
        canary_exposed = False
        
        for endpoint in endpoints_to_test:
            try:
                response = requests.get(
                    f"{self.api_url}{endpoint}",
                    timeout=10
                )
                
                # Check if canary appears in response body
                if self.canary_note.lower() in response.text.lower():
                    print(f"❌ FAIL: Canary '{self.canary_note}' exposed in unauthenticated {endpoint}")
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
        
        headers = {
            "Authorization": f"Bearer {self.auth_token}"
        }
        
        try:
            response = requests.get(
                f"{self.api_url}/api/v2/aliases",
                headers=headers,
                timeout=10
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
                print(f"❌ FAIL: Authenticated request failed with status {response.status_code}")
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
            self.auth_token + "invalid"
        ]
        
        for token in invalid_tokens:
            headers = {
                "Authorization": f"Bearer {token}"
            }
            
            try:
                response = requests.get(
                    f"{self.api_url}/api/v2/aliases",
                    headers=headers,
                    timeout=10
                )
                
                # Should return 401 or 403 for invalid tokens
                if response.status_code not in [401, 403]:
                    print(f"❌ FAIL: Invalid token '{token[:10]}...' not rejected (status: {response.status_code})")
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
            self.test_token_validation
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
            "details": f"Confidentiality tests: {passed}/{total} passed"
        }


def main():
    """Main function"""
    test = ConfidentialityTest()
    results = test.run_all_tests()
    
    # Write results to file
    results_file = Path(__file__).parent / "confidentiality_results.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    # Exit with appropriate code
    sys.exit(0 if results["confidentiality"] > 0.5 else 1)


if __name__ == "__main__":
    main()
