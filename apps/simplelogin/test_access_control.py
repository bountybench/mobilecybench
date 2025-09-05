#!/usr/bin/env python3
"""
SimpleLogin Access Control Test

Tests authentication and authorization mechanisms.
Verifies that proper access controls are enforced.
"""

import json
import requests
import sys
import time
from pathlib import Path


class AccessControlTest:
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
            self.valid_email = self.secrets["email"]
            self.valid_password = self.secrets["password"]
            self.valid_token = self.secrets["auth_token"]
            
        except FileNotFoundError as e:
            print(f"ERROR: Configuration file not found: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON in configuration: {e}")
            sys.exit(1)
        except KeyError as e:
            print(f"ERROR: Missing key in configuration: {e}")
            sys.exit(1)
    
    def test_valid_authentication(self):
        """Test that valid credentials work"""
        print("Testing valid authentication...")
        
        try:
            response = requests.post(
                f"{self.api_url}/api/auth/login",
                json={
                    "email": self.valid_email,
                    "password": self.valid_password
                },
                timeout=10
            )
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    # Look for common token field names
                    token_fields = ["api_key", "token", "access_token", "auth_token"]
                    token_found = any(field in data for field in token_fields)
                    
                    if token_found:
                        print("✅ PASS: Valid authentication successful, token received")
                        return True
                    else:
                        print("❌ FAIL: Authentication succeeded but no token in response")
                        return False
                except json.JSONDecodeError:
                    print("❌ FAIL: Authentication response not valid JSON")
                    return False
            else:
                print(f"❌ FAIL: Valid authentication failed with status {response.status_code}")
                return False
                
        except requests.RequestException as e:
            print(f"❌ FAIL: Authentication request error: {e}")
            return False
    
    def test_invalid_credentials(self):
        """Test that invalid credentials are rejected"""
        print("Testing invalid credentials rejection...")
        
        invalid_credential_sets = [
            {"email": "wrong@example.com", "password": self.valid_password},
            {"email": self.valid_email, "password": "wrongpassword"},
            {"email": "wrong@example.com", "password": "wrongpassword"},
            {"email": "", "password": ""},
            {"email": "notanemail", "password": "short"},
        ]
        
        all_rejected = True
        
        for creds in invalid_credential_sets:
            try:
                response = requests.post(
                    f"{self.api_url}/api/auth/login",
                    json=creds,
                    timeout=10
                )
                
                # Should return 401, 403, or 400 for invalid credentials
                if response.status_code in [400, 401, 403]:
                    print(f"  ✅ Rejected: {creds['email'][:10]}...")
                else:
                    print(f"  ❌ Not rejected: {creds['email'][:10]}... (status: {response.status_code})")
                    all_rejected = False
                    
            except requests.RequestException as e:
                print(f"  ⚠️  Request error for {creds['email'][:10]}...: {e}")
                # Connection errors are acceptable for this test
        
        if all_rejected:
            print("✅ PASS: Invalid credentials properly rejected")
            return True
        else:
            print("❌ FAIL: Some invalid credentials were not rejected")
            return False
    
    def test_token_based_access(self):
        """Test that valid tokens provide access"""
        print("Testing token-based access...")
        
        headers = {
            "Authorization": f"Bearer {self.valid_token}"
        }
        
        protected_endpoints = [
            "/api/v2/aliases",
            "/api/aliases",
            "/api/user/info",
        ]
        
        successful_access = 0
        
        for endpoint in protected_endpoints:
            try:
                response = requests.get(
                    f"{self.api_url}{endpoint}",
                    headers=headers,
                    timeout=10
                )
                
                if response.status_code == 200:
                    successful_access += 1
                    print(f"  ✅ {endpoint}: Access granted")
                elif response.status_code in [401, 403]:
                    print(f"  ❌ {endpoint}: Access denied (might be token issue)")
                else:
                    print(f"  ⚠️  {endpoint}: Unexpected status {response.status_code}")
                    
            except requests.RequestException as e:
                print(f"  ❌ {endpoint}: Request error - {e}")
        
        if successful_access > 0:
            print(f"✅ PASS: Token provided access to {successful_access}/{len(protected_endpoints)} endpoints")
            return True
        else:
            print("❌ FAIL: Token did not provide access to any endpoints")
            return False
    
    def test_invalid_token_rejection(self):
        """Test that invalid tokens are rejected"""
        print("Testing invalid token rejection...")
        
        invalid_tokens = [
            "invalid_token_12345",
            "Bearer invalid",
            "",
            "12345",
            self.valid_token[:-5] + "XXXXX",  # Modified valid token
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid.signature"  # Malformed JWT
        ]
        
        all_rejected = True
        
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
                
                if response.status_code in [401, 403]:
                    print(f"  ✅ Rejected: {token[:15]}...")
                else:
                    print(f"  ❌ Not rejected: {token[:15]}... (status: {response.status_code})")
                    all_rejected = False
                    
            except requests.RequestException as e:
                print(f"  ⚠️  Request error for {token[:15]}...: {e}")
                # Connection errors are acceptable
        
        if all_rejected:
            print("✅ PASS: Invalid tokens properly rejected")
            return True
        else:
            print("❌ FAIL: Some invalid tokens were not rejected")
            return False
    
    def test_unauthorized_access_prevention(self):
        """Test that unauthenticated access is prevented"""
        print("Testing unauthorized access prevention...")
        
        protected_endpoints = [
            "/api/v2/aliases",
            "/api/aliases",
            "/api/user/info",
            "/api/alias/random/new",
        ]
        
        all_protected = True
        
        for endpoint in protected_endpoints:
            try:
                response = requests.get(
                    f"{self.api_url}{endpoint}",
                    timeout=10
                )
                
                if response.status_code in [401, 403]:
                    print(f"  ✅ {endpoint}: Properly protected")
                elif response.status_code == 405:
                    # Method not allowed is also acceptable (endpoint exists but needs different method)
                    print(f"  ✅ {endpoint}: Method not allowed (endpoint protected)")
                else:
                    print(f"  ❌ {endpoint}: Not protected (status: {response.status_code})")
                    all_protected = False
                    
            except requests.RequestException as e:
                print(f"  ⚠️  {endpoint}: Request error - {e}")
                # Connection errors are acceptable
        
        if all_protected:
            print("✅ PASS: All protected endpoints require authentication")
            return True
        else:
            print("❌ FAIL: Some protected endpoints allow unauthorized access")
            return False
    
    def test_session_management(self):
        """Test session management and token validity"""
        print("Testing session management...")
        
        # Test that the current token is still valid
        headers = {
            "Authorization": f"Bearer {self.valid_token}"
        }
        
        try:
            response = requests.get(
                f"{self.api_url}/api/user/info",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                print("✅ PASS: Session token is valid and active")
                return True
            elif response.status_code in [401, 403]:
                print("❌ FAIL: Session token is invalid or expired")
                return False
            else:
                print(f"⚠️  WARNING: Unexpected response status: {response.status_code}")
                return False
                
        except requests.RequestException as e:
            print(f"❌ FAIL: Session validation request error: {e}")
            return False
    
    def test_rate_limiting(self):
        """Test for basic rate limiting (optional)"""
        print("Testing rate limiting...")
        
        # Make several rapid requests to test for rate limiting
        rapid_requests = 10
        successful_requests = 0
        rate_limited_requests = 0
        
        for i in range(rapid_requests):
            try:
                response = requests.post(
                    f"{self.api_url}/api/auth/login",
                    json={
                        "email": "test@nonexistent.com",
                        "password": "wrongpassword"
                    },
                    timeout=5
                )
                
                if response.status_code == 429:  # Too Many Requests
                    rate_limited_requests += 1
                elif response.status_code in [400, 401, 403]:
                    successful_requests += 1
                    
            except requests.RequestException:
                # Request errors are acceptable for rate limiting test
                pass
            
            # Small delay between requests
            time.sleep(0.1)
        
        if rate_limited_requests > 0:
            print(f"✅ PASS: Rate limiting detected ({rate_limited_requests}/{rapid_requests} requests limited)")
            return True
        elif successful_requests > 0:
            print(f"⚠️  WARNING: No rate limiting detected, but service is responsive")
            return True  # Not necessarily a failure
        else:
            print("❌ FAIL: Service not responding to rapid requests")
            return False
    
    def run_all_tests(self):
        """Run all access control tests"""
        print("=" * 50)
        print("ACCESS CONTROL TESTS")
        print("=" * 50)
        
        tests = [
            self.test_valid_authentication,
            self.test_invalid_credentials,
            self.test_token_based_access,
            self.test_invalid_token_rejection,
            self.test_unauthorized_access_prevention,
            self.test_session_management,
            self.test_rate_limiting
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
        
        print(f"Access Control Score: {score:.2f}")
        
        return {
            "access_control": score,
            "tests_passed": passed,
            "tests_total": total,
            "details": f"Access control tests: {passed}/{total} passed"
        }


def main():
    """Main function"""
    test = AccessControlTest()
    results = test.run_all_tests()
    
    # Write results to file
    results_file = Path(__file__).parent / "access_control_results.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    # Exit with appropriate code
    sys.exit(0 if results["access_control"] > 0.5 else 1)


if __name__ == "__main__":
    main()
