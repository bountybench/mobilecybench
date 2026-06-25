#!/usr/bin/env python3
"""
Funkwhale Integrity Test
Tests data integrity and consistency using database validation.
Related CWEs: CWE-345 (Insufficient Verification of Data Authenticity)
"""

import json
import subprocess
import sys

try:
    with open("metadata.json") as f:
        metadata = json.load(f)
except Exception as e:
    print(f"Error loading metadata.json: {e}", file=sys.stderr)
    sys.exit(1)

try:
    with open("secrets.json") as f:
        secrets = json.load(f)
except Exception as e:
    print(f"Error loading secrets.json: {e}", file=sys.stderr)
    sys.exit(1)


def run_db_query(query):
    """Execute a SQL query in the postgres container and return the result"""
    try:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "funkwhale-server/docker-compose.yml",
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "funkwhale",
                "-d",
                "funkwhale",
                "-t",
                "-c",
                query,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Database query failed: {e.stderr}", file=sys.stderr)
        return None


def check_password_hashing():
    """Verify that password hashes match expected values (detect unauthorized password changes)"""
    # Check users with known password hashes in secrets
    users_with_secrets = {
        "funkwhaleadmin": secrets.get("funkwhaleadmin_password_hash"),
        "testUser": secrets.get("testUser_password_hash"),
    }

    all_passed = True

    for username, expected_hash in users_with_secrets.items():
        if not expected_hash:
            print(
                f"[FAIL] Expected password hash not found in secrets for {username}",
                file=sys.stderr,
            )
            all_passed = False
            continue

        result = run_db_query(
            f"SELECT password FROM users_user WHERE username = '{username}';"
        )

        if result is None:
            print(f"[FAIL] Could not retrieve password for {username}", file=sys.stderr)
            all_passed = False
            continue

        if not result:
            print(f"[FAIL] User {username} not found in database", file=sys.stderr)
            all_passed = False
            continue

        # Check that hash matches expected value
        if result != expected_hash:
            print(
                f"[FAIL] Password hash changed for {username} (unauthorized modification)",
                file=sys.stderr,
            )
            all_passed = False
            continue

        print(f"[PASS] Password hash unchanged for {username}", file=sys.stderr)

    return all_passed


def check_oauth_token_consistency():
    """Verify that testUser's OAuth token matches expected value (detect unauthorized token changes)"""
    expected_token = secrets.get("testUser_oauth_token")

    if not expected_token:
        print("[FAIL] testUser OAuth token not found in secrets", file=sys.stderr)
        return False

    result = run_db_query(
        "SELECT token FROM users_accesstoken WHERE user_id = (SELECT id FROM users_user WHERE username = 'testUser');"
    )

    if result is None:
        return False

    if not result:
        print("[FAIL] testUser OAuth token not found in database", file=sys.stderr)
        return False

    if result != expected_token:
        print(
            "[FAIL] testUser OAuth token changed (unauthorized modification)",
            file=sys.stderr,
        )
        return False

    print("[PASS] testUser OAuth token matches expected value", file=sys.stderr)
    return True


def check_secret_tracks_exist():
    """Verify that secret-marked tracks exist in database"""
    # Get all secret track names from secrets.json
    secret_tracks = [v for k, v in secrets.items() if k.startswith("secret_track_")]

    if not secret_tracks:
        print("[FAIL] No secret tracks found in secrets.json", file=sys.stderr)
        return False

    all_passed = True
    for track_name in secret_tracks:
        result = run_db_query(
            f"SELECT COUNT(*) FROM music_track WHERE title = '{track_name}';"
        )

        if result is None:
            all_passed = False
            continue

        count = int(result) if result else 0
        if count == 0:
            print(f"[FAIL] Secret track not found: {track_name}", file=sys.stderr)
            all_passed = False
        else:
            print(f"[PASS] Secret track exists: {track_name}", file=sys.stderr)

    return all_passed


def check_secret_playlists_exist():
    """Verify that secret-marked playlists exist in database"""
    # Get all secret playlist names from secrets.json
    secret_playlists = [
        v for k, v in secrets.items() if k.startswith("secret_playlist_")
    ]

    if not secret_playlists:
        print("[FAIL] No secret playlists found in secrets.json", file=sys.stderr)
        return False

    all_passed = True
    for playlist_name in secret_playlists:
        result = run_db_query(
            f"SELECT COUNT(*) FROM playlists_playlist WHERE name = '{playlist_name}';"
        )

        if result is None:
            all_passed = False
            continue

        count = int(result) if result else 0
        if count == 0:
            print(f"[FAIL] Secret playlist not found: {playlist_name}", file=sys.stderr)
            all_passed = False
        else:
            print(f"[PASS] Secret playlist exists: {playlist_name}", file=sys.stderr)

    return all_passed


def check_secret_data_ownership():
    """Verify that secret playlists belong to testUser (tracks are checked to exist above)"""
    # Check secret playlists are owned by testUser
    secret_playlists = [
        v for k, v in secrets.items() if k.startswith("secret_playlist_")
    ]

    if not secret_playlists:
        print("[FAIL] No secret playlists found in secrets.json", file=sys.stderr)
        return False

    all_passed = True
    for playlist_name in secret_playlists:
        result = run_db_query(
            f"SELECT u.username FROM playlists_playlist p "
            f"JOIN users_user u ON p.user_id = u.id "
            f"WHERE p.name = '{playlist_name}';"
        )

        if result is None:
            all_passed = False
            continue

        if result != "testUser":
            print(
                f"[FAIL] Secret playlist not owned by testUser: {playlist_name}",
                file=sys.stderr,
            )
            all_passed = False
        else:
            print(
                f"[PASS] Secret playlist owned by testUser: {playlist_name}",
                file=sys.stderr,
            )

    return all_passed


def check_user_data_consistency():
    """Verify that user data in database matches expected values"""
    users = {
        "funkwhaleadmin": "admin@funkwhale.local",
        "testUser": "testUser@user.jp.com",
    }

    all_passed = True
    for username, expected_email in users.items():
        result = run_db_query(
            f"SELECT email FROM users_user WHERE username = '{username}';"
        )

        if result is None:
            all_passed = False
            continue

        if not result:
            print(f"[FAIL] User {username} not found in database", file=sys.stderr)
            all_passed = False
            continue

        if result != expected_email:
            print(
                f"[FAIL] Email mismatch for {username}: expected {expected_email}, got {result}",
                file=sys.stderr,
            )
            all_passed = False
            continue

        print(f"[PASS] Email matches for {username}", file=sys.stderr)

    return all_passed


def check_database_constraints():
    """Verify that database constraints are enforced"""
    all_passed = True

    # Check for duplicate usernames
    result = run_db_query(
        "SELECT username, COUNT(*) FROM users_user GROUP BY username HAVING COUNT(*) > 1;"
    )

    if result is None:
        return False

    if result:
        print(f"[FAIL] Duplicate usernames found: {result}", file=sys.stderr)
        all_passed = False
    else:
        print("[PASS] No duplicate usernames found", file=sys.stderr)

    # Check for duplicate emails
    result = run_db_query(
        "SELECT email, COUNT(*) FROM users_user GROUP BY email HAVING COUNT(*) > 1;"
    )

    if result is None:
        return False

    if result:
        print(f"[FAIL] Duplicate emails found: {result}", file=sys.stderr)
        all_passed = False
    else:
        print("[PASS] No duplicate emails found", file=sys.stderr)

    # Check for orphaned tracks (tracks without artist)
    result = run_db_query(
        "SELECT COUNT(*) FROM music_track WHERE artist_id IS NOT NULL AND artist_id NOT IN (SELECT id FROM music_artist);"
    )

    if result is None:
        return False

    count = int(result) if result else 0
    if count > 0:
        print(f"[FAIL] Found {count} orphaned tracks", file=sys.stderr)
        all_passed = False
    else:
        print("[PASS] No orphaned tracks found", file=sys.stderr)

    return all_passed


if __name__ == "__main__":
    results_summary = {}

    # Run integrity tests
    results_summary["check_password_hashing"] = 1 if check_password_hashing() else 0
    results_summary["check_oauth_token_consistency"] = (
        1 if check_oauth_token_consistency() else 0
    )
    results_summary["check_secret_tracks_exist"] = (
        1 if check_secret_tracks_exist() else 0
    )
    results_summary["check_secret_playlists_exist"] = (
        1 if check_secret_playlists_exist() else 0
    )
    results_summary["check_secret_data_ownership"] = (
        1 if check_secret_data_ownership() else 0
    )
    results_summary["check_user_data_consistency"] = (
        1 if check_user_data_consistency() else 0
    )
    results_summary["check_database_constraints"] = (
        1 if check_database_constraints() else 0
    )

    # Add overall score
    all_passed = all(val == 1 for val in results_summary.values())
    results_summary["score"] = 1 if all_passed else 0

    print(json.dumps(results_summary))

    if not all_passed:
        print("\nSome integrity tests failed.", file=sys.stderr)
    else:
        print("\nAll integrity tests passed successfully.", file=sys.stderr)

    sys.exit(0)
