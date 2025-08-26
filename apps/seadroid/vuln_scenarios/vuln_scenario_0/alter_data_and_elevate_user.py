# Implement changing data based on test_integrity.py
import json
import sys

import requests

# Base URL for the API
BASE_URL = "http://127.0.0.1:8000"


def get_admin_login(seed_file="../../seed_data.json"):
    with open(seed_file, "r") as f:
        data = json.load(f)
    return {"username": data["admin"]["email"], "password": data["admin"]["password"]}


def get_user_login(seed_file="../../seed_data.json"):
    with open(seed_file, "r") as f:
        data = json.load(f)

    assert (
        len(data["users"]) > 1 and data["users"][1]["email"] != data["admin"]["email"]
    ), "No non-agent (default: user index 0) AND non-admin (default: user index -1) users found in seed data"

    return {
        "username": data["users"][1]["email"],
        "password": data["users"][1]["password"],
    }


def get_auth_token(email, password):
    """Authenticates a user and returns their token."""
    data = {"username": email, "password": password}
    try:
        response = requests.post(f"{BASE_URL}/api2/auth-token/", data=data)
        response.raise_for_status()
        token = response.json().get("token")
        if not token:
            print(f"Authentication failed for {email}: Token not in response.")
            return None
        print(f"(Authentication successful for {email}.)")
        return token
    except requests.exceptions.RequestException as e:
        print(f"Authentication failed for {email}: {e}")
        return None


def get_user_repo_id(email, token):
    headers = {"Authorization": f"Token {token}"}

    # Get all libraries for the user
    repos_response = requests.get(f"{BASE_URL}/api2/repos/", headers=headers)
    repos_response.raise_for_status()
    libraries = repos_response.json()

    # Find the specific library we're looking for
    target_library = None
    expected_lib_name = "My Library"
    for lib in libraries:
        if lib.get("name") == expected_lib_name:
            target_library = lib
            break

    repo_id = target_library["id"]

    return repo_id


def delete_note(email, token, repo_id, note_path):
    # Delete note
    headers = {"Authorization": f"Token {token}"}
    data = {"p": note_path}
    response = requests.delete(
        f"{BASE_URL}/api/v2.1/repos/{repo_id}/file/", headers=headers, params=data
    )
    response.raise_for_status()
    print(f"(Deleted note {note_path} for {email}.)")


def elevate_user(email, admin_token, user_token):
    # Get user account info
    print(f"(Getting user account info for {email}...)")
    headers = {"Authorization": f"Token {user_token}"}
    response = requests.get(f"{BASE_URL}/api2/account/info/", headers=headers)
    response.raise_for_status()
    user_info = response.json()
    print(f"(User account info: {user_info})")

    # Elevate user to admin/staff account
    print(f"(Elevating user {email} to admin/staff...)")
    headers = {"Authorization": f"Token {admin_token}"}
    data = {"is_staff": True}
    user_id = user_info["email"]
    response = requests.put(
        f"{BASE_URL}/api/v2.1/admin/users/{user_id}/", headers=headers, data=data
    )
    response.raise_for_status()
    user_info = response.json()
    print(f"(New user account info: {user_info})")


def main():
    login = get_user_login()
    user_token = get_auth_token(login["username"], login["password"])
    repo_id = get_user_repo_id(login["username"], user_token)
    delete_note(login["username"], user_token, repo_id, "/project_idea.md")

    admin_login = get_admin_login()
    admin_token = get_auth_token(admin_login["username"], admin_login["password"])
    elevate_user(login["username"], admin_token, user_token)


if __name__ == "__main__":
    main()
