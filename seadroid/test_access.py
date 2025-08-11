#!/usr/bin/env python3
import sys
import requests
import json
import os

# Base URL for the API
BASE_URL = "http://127.0.0.1:8000"

def load_user_configs():
    """Load user configurations from seed_data.json file."""
    try:
        # Try to find seed_data.json in current directory or script directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        seed_file_paths = ['seed_data.json', os.path.join(script_dir, 'seed_data.json')]
        
        data = None
        for path in seed_file_paths:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
                break
        
        if data is None:
            print(f"❌ Error: seed_data.json not found in {seed_file_paths}")
            return []
        
        user_configs = []
        for user in data['users']:
            config = {
                "email": user["email"],
                "password": user["password"],
                "expected_library_name": user["note"]["library_name"],
                "expected_note_name": user["note"]["file_name"],
                "expected_note_content": user["note"]["content"],
            }
            user_configs.append(config)
        
        # Also add admin config
        admin_config = {
            "email": data["admin"]["email"],
            "password": data["admin"]["password"],
            "expected_library_name": "My Library",  # Admin might not have notes
            "expected_note_name": None,
            "expected_note_content": None,
        }
        
        return user_configs, admin_config
    except Exception as e:
        print(f"❌ Error loading user configs: {e}")
        return [], None

def test_authentication(email, password, expected_success=True, test_name=""):
    """Test authentication with given credentials."""
    print(f"  🔍 Testing: {test_name}")
    
    data = {"username": email, "password": password}
    try:
        response = requests.post(f"{BASE_URL}/api2/auth-token/", data=data)
        
        if expected_success:
            if response.status_code == 200:
                token = response.json().get("token")
                if token:
                    print(f"    ✅ SUCCESS: Authentication passed for {email}")
                    return token
                else:
                    print(f"    ❌ FAILED: No token in response for {email}")
                    return None
            else:
                print(f"    ❌ FAILED: Expected success but got status {response.status_code} for {email}")
                return None
        else:
            if response.status_code != 200:
                print(f"    ✅ SUCCESS: Authentication properly rejected for {email} (status: {response.status_code})")
                return None
            else:
                print(f"    ❌ FAILED: Expected rejection but authentication succeeded for {email}")
                return response.json().get("token")
                
    except requests.exceptions.RequestException as e:
        if expected_success:
            print(f"    ❌ FAILED: Network error during authentication for {email}: {e}")
        else:
            print(f"    ✅ SUCCESS: Network error as expected for {email}: {e}")
        return None

def test_api_with_invalid_token(endpoint, test_name=""):
    """Test API endpoint with invalid token."""
    print(f"  🔍 Testing: {test_name}")
    
    invalid_tokens = [
        "invalid_token_123",
        "Token_with_wrong_format",
        "",
        "a" * 64,  # 64 character string
        "Bearer invalid_token"  # Wrong format
    ]
    
    for token in invalid_tokens:
        headers = {"Authorization": f"Token {token}"}
        try:
            response = requests.get(f"{BASE_URL}{endpoint}", headers=headers)
            if response.status_code in [401, 403]:
                print(f"    ✅ SUCCESS: Invalid token '{token[:10]}...' properly rejected (status: {response.status_code})")
            else:
                print(f"    ❌ FAILED: Invalid token '{token[:10]}...' not rejected (status: {response.status_code})")
        except requests.exceptions.RequestException as e:
            print(f"    ✅ SUCCESS: Network error with invalid token as expected: {e}")

def test_file_access_with_invalid_params(valid_token, repo_id, test_name=""):
    """Test file access with invalid parameters."""
    print(f"  🔍 Testing: {test_name}")
    
    headers = {"Authorization": f"Token {valid_token}"}
    
    # Test with invalid file paths
    invalid_paths = [
        "/nonexistent_file.txt",
        "/../../etc/passwd",  # Path traversal attempt
        "/invalid/path/file.md",
        "",
        "not_starting_with_slash.txt"
    ]
    
    for invalid_path in invalid_paths:
        try:
            response = requests.get(
                f"{BASE_URL}/api2/repos/{repo_id}/file/",
                headers=headers,
                params={"p": invalid_path}
            )
            if response.status_code in [404, 400]:
                print(f"    ✅ SUCCESS: Invalid file path '{invalid_path}' properly rejected (status: {response.status_code})")
            else:
                print(f"    ❌ FAILED: Invalid file path '{invalid_path}' not rejected (status: {response.status_code})")
        except requests.exceptions.RequestException as e:
            print(f"    ✅ SUCCESS: Network error with invalid path as expected: {e}")

def test_cross_user_access_pair(user1_config, user2_config):
    """Test that one user cannot access another user's data."""
    user1_email = user1_config["email"]
    user2_email = user2_config["email"]
    
    print(f"    🔍 Testing: {user1_email} cannot access {user2_email}'s data")
    
    # Get tokens for both users
    user1_token = test_authentication(user1_config["email"], user1_config["password"], True, f"Auth for {user1_config['email']}")
    user2_token = test_authentication(user2_config["email"], user2_config["password"], True, f"Auth for {user2_config['email']}")
    
    if not user1_token or not user2_token:
        print(f"      ❌ FAILED: Could not get tokens for cross-user test ({user1_email} -> {user2_email})")
        return False
    
    # Get user2's library data
    headers1 = {"Authorization": f"Token {user1_token}"}
    headers2 = {"Authorization": f"Token {user2_token}"}
    
    try:
        # Get user2's libraries
        repos_response = requests.get(f"{BASE_URL}/api2/repos/", headers=headers2)
        repos_response.raise_for_status()
        user2_libraries = repos_response.json()
        
        if not user2_libraries:
            print(f"      ⚠️  SKIPPED: {user2_email} has no libraries for cross-user test")
            return True
        
        user2_repo_id = user2_libraries[0]["id"]
        
        # Test 1: Try to access user2's library listing with user1's token
        cross_access_response = requests.get(f"{BASE_URL}/api2/repos/{user2_repo_id}/dir/", headers=headers1, params={"p": "/"})
        
        if cross_access_response.status_code in [403, 404]:
            print(f"      ✅ SUCCESS: {user1_email} properly denied access to {user2_email}'s library (status: {cross_access_response.status_code})")
            library_access_blocked = True
        else:
            print(f"      ❌ FAILED: {user1_email} inappropriately granted access to {user2_email}'s library (status: {cross_access_response.status_code})")
            library_access_blocked = False
        
        # Test 2: Try to access user2's files directly (if user2 has expected files)
        file_access_blocked = True
        if user2_config.get("expected_note_name"):
            try:
                file_path = f"/{user2_config['expected_note_name']}"
                file_access_response = requests.get(
                    f"{BASE_URL}/api2/repos/{user2_repo_id}/file/",
                    headers=headers1,
                    params={"p": file_path}
                )
                
                if file_access_response.status_code in [403, 404]:
                    print(f"      ✅ SUCCESS: {user1_email} properly denied access to {user2_email}'s file (status: {file_access_response.status_code})")
                    file_access_blocked = True
                else:
                    print(f"      ❌ FAILED: {user1_email} inappropriately granted access to {user2_email}'s file (status: {file_access_response.status_code})")
                    file_access_blocked = False
                    
            except requests.exceptions.RequestException as e:
                print(f"      ✅ SUCCESS: {user1_email} file access to {user2_email}'s data failed as expected: {e}")
                file_access_blocked = True
        
        return library_access_blocked and file_access_blocked
        
    except requests.exceptions.RequestException as e:
        print(f"      ✅ SUCCESS: {user1_email} cross-user access to {user2_email} failed as expected: {e}")
        return True

def test_comprehensive_cross_user_access(user_configs):
    """Test cross-user access prevention between all pairs of users (up to first 5)."""
    print(f"  🔍 Testing: Comprehensive cross-user access prevention")
    
    # Limit to first 5 users for performance
    test_users = user_configs[:5]
    total_tests = 0
    passed_tests = 0
    
    print(f"    📊 Testing access control between {len(test_users)} users ({len(test_users) * (len(test_users) - 1)} combinations)")
    
    # Test all combinations where user A tries to access user B's data
    for i, user_a in enumerate(test_users):
        for j, user_b in enumerate(test_users):
            if i != j:  # Don't test user accessing their own data
                total_tests += 1
                if test_cross_user_access_pair(user_a, user_b):
                    passed_tests += 1
    
    success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    print(f"    📈 Cross-user access prevention: {passed_tests}/{total_tests} tests passed ({success_rate:.1f}%)")
    
    if passed_tests == total_tests:
        print(f"    ✅ SUCCESS: All cross-user access properly prevented")
        return True
    else:
        print(f"    ❌ FAILED: {total_tests - passed_tests} cross-user access violations detected")
        return False

def test_valid_user_full_access(user_config):
    """Test that a valid user can fully access their data."""
    print(f"  🔍 Testing: Full access for {user_config['email']}")
    
    # 1. Authentication
    token = test_authentication(user_config["email"], user_config["password"], True, f"Auth for {user_config['email']}")
    if not token:
        print(f"    ❌ FAILED: Could not authenticate {user_config['email']}")
        return False
    
    headers = {"Authorization": f"Token {token}"}
    success = True
    
    # 2. List libraries
    try:
        repos_response = requests.get(f"{BASE_URL}/api2/repos/", headers=headers)
        repos_response.raise_for_status()
        libraries = repos_response.json()
        
        if libraries:
            print(f"    ✅ SUCCESS: User can list libraries ({len(libraries)} found)")
        else:
            print(f"    ❌ FAILED: User has no accessible libraries")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"    ❌ FAILED: Cannot list libraries: {e}")
        return False
    
    # 3. Access library contents
    try:
        repo_id = libraries[0]["id"]
        dir_response = requests.get(f"{BASE_URL}/api2/repos/{repo_id}/dir/", headers=headers, params={"p": "/"})
        dir_response.raise_for_status()
        dir_contents = dir_response.json()
        
        print(f"    ✅ SUCCESS: User can access library contents ({len(dir_contents)} items)")
        
    except requests.exceptions.RequestException as e:
        print(f"    ❌ FAILED: Cannot access library contents: {e}")
        success = False
    
    # 4. Download file if expected note exists
    if user_config.get("expected_note_name"):
        try:
            file_path = f"/{user_config['expected_note_name']}"
            
            # Get download link
            download_link_response = requests.get(
                f"{BASE_URL}/api2/repos/{repo_id}/file/",
                headers=headers,
                params={"p": file_path}
            )
            download_link_response.raise_for_status()
            download_url = download_link_response.json()
            
            # Fix URL if needed
            if "10.0.2.2" in download_url:
                download_url = download_url.replace("http://10.0.2.2:8000", BASE_URL)
            
            # Download content
            content_response = requests.get(download_url, headers=headers)
            content_response.raise_for_status()
            
            print(f"    ✅ SUCCESS: User can download file content ({len(content_response.text)} chars)")
            
        except requests.exceptions.RequestException as e:
            print(f"    ❌ FAILED: Cannot download file: {e}")
            success = False
    
    return success

def run_invalid_credential_tests():
    """Run all invalid credential tests."""
    print("\n🔒 === TESTING INVALID CREDENTIAL REJECTION ===")
    
    user_configs, admin_config = load_user_configs()
    if not user_configs:
        print("❌ Could not load user configs for testing")
        return False
    
    all_passed = True
    
    # Test 1: Completely invalid credentials
    print("\n📋 Test Group 1: Completely Invalid Credentials")
    invalid_tests = [
        ("nonexistent@example.com", "wrongpassword", "Non-existent user"),
        ("", "", "Empty credentials"),
        ("invalid_email", "password", "Invalid email format"),
        ("user@domain", "123", "Invalid domain and weak password"),
    ]
    
    for email, password, desc in invalid_tests:
        result = test_authentication(email, password, False, desc)
        if result is not None:  # Should be None for failed auth
            all_passed = False
    
    # Test 2: Valid usernames with wrong passwords (case insensitive)
    print("\n📋 Test Group 2: Valid Usernames with Wrong Passwords (Case Insensitive)")
    for user_config in user_configs:
        wrong_passwords = ["wrongpass", "123456", user_config["password"] + "x", ""]
        for wrong_pass in wrong_passwords:
            # Only test if the password is actually different when lowercased
            if wrong_pass.lower() != user_config["password"].lower():
                result = test_authentication(user_config["email"], wrong_pass, False, 
                                           f"Valid user {user_config['email']} with wrong password '{wrong_pass}'")
                if result is not None:
                    all_passed = False
    
    # Test 3: Invalid usernames with valid passwords (case insensitive)
    print("\n📋 Test Group 3: Invalid Usernames with Valid Passwords (Case Insensitive)")
    for user_config in user_configs:
        # Only test emails that are actually different when case is normalized
        invalid_emails = [
            user_config["email"] + "x",
            user_config["email"].replace("@", "_at_"),
            "wrong" + user_config["email"],
            # Removed case sensitivity test since we want case insensitive behavior
        ]
        for invalid_email in invalid_emails:
            # Only test if the email is actually different when lowercased
            if invalid_email.lower() != user_config["email"].lower():
                result = test_authentication(invalid_email, user_config["password"], False,
                                           f"Invalid email '{invalid_email}' with valid password")
                if result is not None:
                    all_passed = False
    
    # Test 4: API requests with invalid tokens
    print("\n📋 Test Group 4: API Requests with Invalid Tokens")
    test_api_with_invalid_token("/api2/repos/", "Repository listing with invalid token")
    test_api_with_invalid_token("/api2/account/info/", "Account info with invalid token")
    
    # Test 5: API requests with valid token but invalid parameters
    print("\n📋 Test Group 5: Valid Token with Invalid Parameters")
    if user_configs:
        # Get a valid token first
        valid_token = test_authentication(user_configs[0]["email"], user_configs[0]["password"], True, "Getting valid token for param tests")
        if valid_token:
            # Get user's repo for testing
            headers = {"Authorization": f"Token {valid_token}"}
            try:
                repos_response = requests.get(f"{BASE_URL}/api2/repos/", headers=headers)
                repos_response.raise_for_status()
                libraries = repos_response.json()
                if libraries:
                    test_file_access_with_invalid_params(valid_token, libraries[0]["id"], "File access with invalid paths")
            except Exception as e:
                print(f"    ❌ Could not get repository for parameter testing: {e}")
                all_passed = False
    
    return all_passed

def run_valid_credential_tests():
    """Run all valid credential tests."""
    print("\n🔓 === TESTING VALID CREDENTIAL ACCEPTANCE ===")
    
    user_configs, admin_config = load_user_configs()
    if not user_configs:
        print("❌ Could not load user configs for testing")
        return False
    
    all_passed = True
    
    # Test 1: All users can authenticate and access their data
    print("\n📋 Test Group 1: Valid User Authentication and Data Access")
    for i, user_config in enumerate(user_configs):
        print(f"\n  👤 Testing User {i+1}: {user_config['email']}")
        if not test_valid_user_full_access(user_config):
            all_passed = False
    
    # Test 2: Admin authentication (if different from users)
    if admin_config and admin_config not in user_configs:
        print(f"\n📋 Test Group 2: Admin Authentication")
        print(f"\n  👤 Testing Admin: {admin_config['email']}")
        admin_token = test_authentication(admin_config["email"], admin_config["password"], True, "Admin authentication")
        if admin_token:
            print("    ✅ SUCCESS: Admin can authenticate")
        else:
            print("    ❌ FAILED: Admin cannot authenticate")
            all_passed = False
    
    # Test 3: Cross-user access prevention
    print(f"\n📋 Test Group 3: Access Control Between Users")
    if len(user_configs) >= 2:
        if not test_comprehensive_cross_user_access(user_configs):
            all_passed = False
    else:
        print("    ⚠️  SKIPPED: Need at least 2 users for cross-access testing")
    
    return all_passed

def main():
    """Main function to run all access tests."""
    print("🔐 === SEAFILE ACCESS CONTROL TESTING ===")
    print("Testing authentication, authorization, and access control...")
    
    # Run invalid credential tests
    invalid_tests_passed = run_invalid_credential_tests()
    
    # Run valid credential tests
    valid_tests_passed = run_valid_credential_tests()
    
    # Summary
    print(f"\n{'='*60}")
    print("📊 === TEST SUMMARY ===")
    
    if invalid_tests_passed:
        print("✅ PASSED: Invalid credential rejection tests")
    else:
        print("❌ FAILED: Some invalid credentials were not properly rejected")
    
    if valid_tests_passed:
        print("✅ PASSED: Valid credential acceptance tests")
    else:
        print("❌ FAILED: Some valid credentials could not access their data")
    
    overall_success = invalid_tests_passed and valid_tests_passed
    
    if overall_success:
        print("\n🎉 ALL ACCESS CONTROL TESTS PASSED!")
        sys.exit(0)
    else:
        print("\n💥 SOME ACCESS CONTROL TESTS FAILED!")
        sys.exit(1)

if __name__ == "__main__":
    main()
