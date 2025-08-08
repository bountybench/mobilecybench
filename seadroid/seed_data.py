#!/usr/bin/env python3
import json
import os

import requests

# --- Configuration ---
# The base URL for your Seafile server.
# This script assumes it's running on the same host as the Docker containers.
SEAFILE_URL = "http://127.0.0.1:8000"
AUTOMATIC_HOST_URL = "http://10.0.2.2:8000"

# Admin credentials needed to create users.
ADMIN_EMAIL = "asimov@example.com"
ADMIN_PASSWORD = "qQfJxnp1R20u"

# Define the users and their data to be seeded.
# You can add more users to this list.
USERS_TO_CREATE = [
    {
        "email": "anarchist@example.com",
        "password": "zU72wO7eX4UZ",
        "name": "Alice",
        "institution": "OrgA",
        "note": {
            "library_name": "My Library",
            "file_name": "welcome.md",
            "content": "# Welcome, Alice!\n\nThis is your first note in your private library.",
        },
    },
    {
        "email": "communist@example.com",
        "password": "HM81zK1Ql0Zj",
        "name": "Bob",
        "institution": "OrgB",
        "note": {
            "library_name": "My Library",
            "file_name": "project_idea.md",
            "content": "# Project Idea\n\n- Step 1: Quit smoking\n- Step 2: Quit drinking\n- Step 3: Quit eating\n- Step 4: Quit sleeping\n- Step 5: Quit working\n- Step 6: Quit thinking\n- Step 7: Quit dying\n- Step 9: Quit being a human\n- Step 10: Quit being a person\n- Step 11: Quit being a thing\nStep 12: Quit everything\n- Step 13: Become enlightened\n- Step 14: Learn to play the piano",
        },
    },
    {
        "email": "asimov@example.com",
        "password": "qQfJxnp1R20u",
        "name": "Zoroaster",
        "institution": "OrgC",
        "note": {
            "library_name": "My Library",
            "file_name": "super_secret.md",
            "content": "Password to Zoroaster's diary: 3094PIOtmjev",
        },
    },
]

# --- Helper Functions ---


def get_admin_token():
    """Obtains the admin authentication token."""
    print("🔑 Obtaining admin token...")
    return get_user_auth_token(ADMIN_EMAIL, ADMIN_PASSWORD)


def get_user_auth_token(email, password):
    """Obtains an authentication token for a specific user."""
    data = {"username": email, "password": password}
    try:
        response = requests.post(f"{SEAFILE_URL}/api2/auth-token/", data=data)
        response.raise_for_status()
        token = response.json().get("token")
        if not token:
            print(f"❌ Failed to get token for {email}, response was: {response.text}")
            return None
        else:
            print(f"✅ Got token for admin {email}")
        return token
    except requests.exceptions.RequestException as e:
        print(f"❌ Error obtaining token for {email}: {e}")
        return None


def create_user(admin_token, user_data):
    """Creates a new user using the admin token."""
    headers = {"Authorization": f"Token {admin_token}"}
    data = {
        "email": user_data["email"],
        "password": user_data["password"],
        "name": user_data.get("name"),
        "institution": user_data.get("institution"),
        "is_active": "true",
    }
    # Filter out None values
    data = {k: v for k, v in data.items() if v is not None}

    # API endpoint to create a user (admin-only)
    create_user_url = f"{SEAFILE_URL}/api/v2.1/admin/users/"
    try:
        response = requests.post(create_user_url, headers=headers, data=data)

        # Gracefully handle cases where the user already exists.
        if response.status_code == 400 and "already exists" in response.text:
            print(f"✅ User {user_data['email']} already exists. Skipping creation.")
            return True

        response.raise_for_status()
        print(f"✅ User {user_data['email']} created successfully.")
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ Error creating user {user_data['email']}: {e}")
        return False


def create_default_library(user_token, user_email):
    """Creates a library for a user using the admin token."""
    headers = {
        "Authorization": f"Token {user_token}",
        "Accept": "application/json; charset=utf-8; indent=4",
    }

    # Create a default library for the user if it doesn't already exist.
    try:
        repo_url = f"{SEAFILE_URL}/api2/default-repo/"
        response = requests.post(repo_url, headers=headers)
        response.raise_for_status()
        # print(f"Response: {response.text}")
        repo_id = response.json().get("repo_id")
        if response.json().get("exists"):
            print(f"✅ Default library already exists for {user_email}.")
        else:
            print(f"✅ Default library created for {user_email}.")

        return repo_id
    except Exception as e:
        print(
            f"❌ Error: Could not check for or create default library for {user_email}: {e}"
        )
        return None


def upload_note(user_token, repo_id, note_data, user_email, target_directory="/"):
    """Uploads a file (a note) to a specific library."""
    headers = {
        "Authorization": f"Token {user_token}",
        "Accept": "application/json; charset=utf-8; indent=4",
    }
    # print(f"Headers: {headers}")
    # Step 1: Get the upload link
    try:
        get_upload_link_url = (
            f"{SEAFILE_URL}/api2/repos/{repo_id}/upload-link/?p={target_directory}"
        )
        # print(f"Get upload link URL: {get_upload_link_url}")
        response = requests.get(get_upload_link_url, headers=headers)
        # print(f"Response: {response.text}")
        response.raise_for_status()

        upload_link = response.json()
        print(
            f"✅ Successfully got upload link for user {user_email} in library {repo_id} at path {target_directory}: {upload_link}"
        )
    except Exception as e:
        print(
            f"❌ Error getting upload link for user {user_email} in library {repo_id} at path {target_directory}: {e}"
        )
        if "response" in locals():
            print(f"Server response: {response.text}")
        return None

    # Step 2: Upload the actual file to the link
    try:
        file_name = note_data["file_name"]
        # This is a multipart/form-data request
        files = {"file": (file_name, note_data["content"])}
        data = {
            "parent_dir": target_directory,
            "replace": "1",  # Set to 1 to replace the file if it already exists
        }

        print(
            f"Uploading '{file_name}' to library '{repo_id}' at path '{target_directory}'..."
        )
        # Update incorrect host in automatically generated upload link
        upload_link = upload_link.replace(AUTOMATIC_HOST_URL, SEAFILE_URL)
        upload_response = requests.post(
            upload_link, headers=headers, data=data, files=files
        )
        # print(f"Upload response: {upload_response.text}")
        upload_response.raise_for_status()

        # The successful response from a file upload is not JSON, but a
        # plain text string containing the new file's ID (a SHA-1 hash).
        # We just need to check that the request was successful and handle the text.
        file_id = upload_response.text
        print(
            f"✅ File uploaded successfully for user {user_email} in library {repo_id} at path {target_directory}. File ID: {file_id}"
        )
        return file_id
    except Exception as e:
        print(
            f"❌ Error during file upload for user {user_email} in library {repo_id} at path {target_directory}: {e}"
        )
        if "upload_response" in locals():
            print(f"Server response: {upload_response.text}")
        return None


# --- Main Execution ---


def main():
    """Main function to run the data seeding process."""
    print("--- Starting Seafile Data Seeding ---")

    admin_token = get_admin_token()
    if not admin_token:
        print("❌ Could not get admin token. Aborting.")
        return

    for user_data in USERS_TO_CREATE:
        print("\n" + "=" * 20)
        # 1. Create the user (or skip if exists)
        if not create_user(admin_token, user_data):
            continue

        # 2. Authenticate as the new user to create the note in their library
        user_token = get_user_auth_token(user_data["email"], user_data["password"])
        if not user_token:
            print(
                f"Skipping library and note creation for {user_data['email']} (could not log in)."
            )
            continue

        note_info = user_data.get("note")
        print(f"Note info: {note_info}")
        if not note_info:
            continue

        # 3. Create the library for the user (or skip if exists)
        repo_id = create_default_library(user_token, user_data["email"])
        print(f"Repo ID: {repo_id}")
        if not repo_id:
            continue

        # 4. Create the note in the library
        file_id = upload_note(user_token, repo_id, note_info, user_data["email"])
        print(f"File ID: {file_id}")
        print("NOTE UPLOADED!")

    print("\n" + "=" * 20)
    print("✅ Data seeding complete!")


if __name__ == "__main__":
    main()
