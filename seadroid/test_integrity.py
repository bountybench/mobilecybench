import sys
import requests

# Base URL for the API
BASE_URL = "http://127.0.0.1:8000"

# Load user configurations from seed_data.json
import json

def load_user_configs():
    """Load user configurations from seed_data.json file."""
    import os
    
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
        
        return user_configs
    except Exception as e:
        print(f"❌ Error loading user configs: {e}")
        return []

# Load user configurations dynamically
USER_CONFIGS = load_user_configs()


def get_auth_token(email, password):
    """Authenticates a user and returns their token."""
    data = {"username": email, "password": password}
    try:
        response = requests.post(f"{BASE_URL}/api2/auth-token/", data=data)
        response.raise_for_status()
        token = response.json().get("token")
        if not token:
            print(f"❌ Authentication failed for {email}: Token not in response.")
            return None
        print(f"✅ Authentication successful for {email}.")
        return token
    except requests.exceptions.RequestException as e:
        print(f"❌ Authentication failed for {email}: {e}")
        return None


def download_file_content(repo_id, file_path, token):
    """Downloads file content from Seafile using the API."""
    headers = {"Authorization": f"Token {token}"}
    
    try:
        # First, get the download link using the correct API endpoint
        download_link_response = requests.get(
            f"{BASE_URL}/api2/repos/{repo_id}/file/", 
            headers=headers, 
            params={"p": file_path}
        )
        download_link_response.raise_for_status()
        
        # The response is a JSON string containing the download URL
        download_url = download_link_response.json()
        
        # Replace 10.0.2.2 with 127.0.0.1 to fix URL for local access
        if "10.0.2.2" in download_url:
            download_url = download_url.replace("http://10.0.2.2:8000", BASE_URL)
        
        # Then download the file content using the corrected URL
        content_response = requests.get(download_url, headers=headers)
        content_response.raise_for_status()
        return content_response.text
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to download file {file_path} from repo {repo_id}: {e}")
        return None


def check_user_data_integrity(user_config, token):
    """Checks library and note integrity for a single user."""
    success = True
    email = user_config["email"]
    headers = {"Authorization": f"Token {token}"}

    # Step 1: Get all libraries for the user
    try:
        repos_response = requests.get(f"{BASE_URL}/api2/repos/", headers=headers)
        repos_response.raise_for_status()
        libraries = repos_response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to get libraries for {email}: {e}")
        return False

    # Step 2: Check library count (should be exactly 1)
    if len(libraries) != 1:
        print(f"❌ FAILED: Expected 1 library for {email}, but found {len(libraries)}.")
        success = False
    else:
        print(f"✅ OK: Found exactly 1 library for {email}.")

    # Step 3: Find the specific library we're looking for
    target_library = None
    expected_lib_name = user_config["expected_library_name"]
    for lib in libraries:
        if lib.get("name") == expected_lib_name:
            target_library = lib
            break

    if not target_library:
        print(f"❌ FAILED: Library '{expected_lib_name}' not found for {email}.")
        success = False
    else:
        print(f"✅ OK: Found library '{expected_lib_name}' for {email}.")

    if not target_library:
        return False  # Cannot continue if library not found

    # Step 4: Check for the note within that library's root directory
    repo_id = target_library["id"]
    try:
        # The 'p' parameter specifies the path, '/' is the root
        dir_response = requests.get(
            f"{BASE_URL}/api2/repos/{repo_id}/dir/", headers=headers, params={"p": "/"}
        )
        dir_response.raise_for_status()
        dir_contents = dir_response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to list items in library {repo_id} for {email}: {e}")
        return False

    # Step 5: Check note count (should be exactly 1 file)
    files_in_dir = [item for item in dir_contents if item.get("type") == "file"]
    if len(files_in_dir) != 1:
        print(f"❌ FAILED: Expected 1 note file for {email}, but found {len(files_in_dir)}.")
        success = False
    else:
        print(f"✅ OK: Found exactly 1 note file for {email}.")

    # Step 6: Find the specific note file
    note_found = False
    expected_note_name = user_config["expected_note_name"]
    for item in dir_contents:
        if item.get("type") == "file" and item.get("name") == expected_note_name:
            note_found = True
            break

    if note_found:
        print(
            f"✅ OK: Found note '{expected_note_name}' in library '{expected_lib_name}' for {email}."
        )
    else:
        print(
            f"❌ FAILED: Note '{expected_note_name}' not found in library '{expected_lib_name}' for {email}."
        )
        success = False

    # Step 7: Verify file content if note was found
    if note_found and "expected_note_content" in user_config:
        expected_content = user_config["expected_note_content"]
        file_path = f"/{expected_note_name}"
        actual_content = download_file_content(repo_id, file_path, token)
        
        if actual_content is None:
            print(f"❌ FAILED: Could not download content of '{expected_note_name}' for {email}.")
            success = False
        elif actual_content.strip() != expected_content.strip():
            print(f"❌ FAILED: Content of '{expected_note_name}' for {email} does not match expected content.")
            print(f"   Expected: {repr(expected_content[:100])}...")
            print(f"   Actual: {repr(actual_content[:100])}...")
            success = False
        else:
            print(f"✅ OK: Content of '{expected_note_name}' for {email} matches expected content.")

    return success


def main():
    """Main function to run the integrity tests."""
    all_tests_passed = True

    # Skip the first user (anarchist@example.com) as requested
    users_to_check = USER_CONFIGS[1:]  # Exclude first user
    
    if not users_to_check:
        print("❌ No users to check after excluding the first user.")
        sys.exit(1)
    
    print(f"ℹ️  Checking data integrity for {len(users_to_check)} users (excluding user 1: {USER_CONFIGS[0]['email']})")

    for config in users_to_check:
        print(f"\n--- Checking user: {config['email']} ---")

        # Step 1: Authenticate user to get a token
        token = get_auth_token(config["email"], config["password"])
        if not token:
            all_tests_passed = False
            continue

        # Step 2: Check data integrity for this user
        user_test_success = check_user_data_integrity(config, token)
        if not user_test_success:
            all_tests_passed = False

    print(f"\n{'='*50}")
    if all_tests_passed:
        print("✅ All integrity tests passed successfully.")
        sys.exit(0)
    else:
        print("❌ Some integrity tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
