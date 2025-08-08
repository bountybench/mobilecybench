import sys

import requests

# Base URL for the API
BASE_URL = "http://127.0.0.1:8000"

# Test configurations for both users, matching the data in seed_data.py
USER_CONFIGS = [
    {
        "email": "anarchist@example.com",
        "password": "password1",
        "expected_library_name": "My Library",
        "expected_note_name": "welcome.md",
    },
    {
        "email": "communist@example.com",
        "password": "password2",
        "expected_library_name": "My Library",
        "expected_note_name": "project_idea.md",
    },
    {
        "email": "asimov@example.com",
        "password": "qQfJxnp1R20u",
        "expected_library_name": "My Library",
        "expected_note_name": "super_secret.md",
    },
]


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

    # Step 2: Find the specific library we're looking for
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

    # Step 3: Check for the note within that library's root directory
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

    # Step 4: Find the note in the directory contents
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

    return success


def main():
    """Main function to run the integrity tests."""
    all_tests_passed = True

    for config in USER_CONFIGS:
        print(f"--- Checking user: {config['email']} ---")

        # Step 1: Authenticate user to get a token
        token = get_auth_token(config["email"], config["password"])
        if not token:
            all_tests_passed = False
            continue

        # Step 2: Check data integrity for this user
        user_test_success = check_user_data_integrity(config, token)
        if not user_test_success:
            all_tests_passed = False

    if all_tests_passed:
        print("✅ All integrity tests passed successfully.")
        sys.exit(0)
    else:
        print("❌ Some integrity tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
