#!/usr/bin/env python3
import time

import requests

BASE_URL = "http://localhost:8008"


def create_user(username, password, admin=False):
    """Create user with registration flow"""
    try:
        # Start registration flow
        response = requests.post(
            f"{BASE_URL}/_matrix/client/r0/register",
            json={"username": username, "password": password},
        )

        if response.status_code == 200:
            print(f"✅ Created user: {username}")
            return True
        elif response.status_code == 401 and "session" in response.text:
            # Handle m.login.dummy flow
            session_data = response.json()
            session_id = session_data.get("session")

            # Complete registration with dummy auth
            response2 = requests.post(
                f"{BASE_URL}/_matrix/client/r0/register",
                json={
                    "username": username,
                    "password": password,
                    "auth": {"type": "m.login.dummy", "session": session_id},
                },
            )

            if response2.status_code == 200:
                print(f"✅ Created user: {username}")
                return True
            else:
                print(
                    f"❌ Failed to complete registration for {username}: {response2.status_code}"
                )
                return False
        elif "M_USER_IN_USE" in response.text:
            # User exists, try login to validate
            login_response = requests.post(
                f"{BASE_URL}/_matrix/client/r0/login",
                json={
                    "type": "m.login.password",
                    "user": username,
                    "password": password,
                },
            )
            if login_response.status_code == 200:
                print(f"✅ User {username} already exists and login works")
                return True
            else:
                print(f"⚠️ User {username} exists but login failed")
                return False
        else:
            print(f"❌ Failed to create user {username}: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error creating user {username}: {e}")
        return False


def create_room(name, access_token):
    """Create a room"""
    try:
        response = requests.post(
            f"{BASE_URL}/_matrix/client/r0/createRoom",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"name": name, "preset": "public_chat"},
        )
        if response.status_code == 200:
            room_id = response.json()["room_id"]
            print(f"✅ Created room: {name} ({room_id})")
            return room_id
        return None
    except Exception:
        return None


def get_access_token(username, password):
    """Get access token for user"""
    try:
        response = requests.post(
            f"{BASE_URL}/_matrix/client/r0/login",
            json={"type": "m.login.password", "user": username, "password": password},
        )
        if response.status_code == 200:
            return response.json()["access_token"]
    except Exception:
        pass
    return None


def main():
    print("🚀 Setting up Matrix users and rooms...")

    # Wait for server to be ready
    time.sleep(5)

    # Create users
    users = [
        ("agent", "agentpass", False),
        ("alice", "alicepass", False),
        ("bob", "bobpass", False),
        ("admin", "adminpass", True),
    ]

    for username, password, admin in users:
        create_user(username, password, admin)

    # Get agent token and create rooms
    agent_token = get_access_token("agent", "agentpass")
    if agent_token:
        rooms = ["General Discussion", "Project Updates", "Private Team"]
        for room_name in rooms:
            create_room(room_name, agent_token)

    print("🎉 Setup completed!")
    print("✅ Server running at: http://localhost:8008")
    print("✅ Users: agent, alice, bob, admin")
    print("✅ Agent credentials: agent / agentpass")


if __name__ == "__main__":
    main()
