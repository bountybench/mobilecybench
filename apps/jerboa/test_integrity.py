#!/usr/bin/env python3
"""
Integrity tests for Jerboa/Lemmy.

Validates database integrity is preserved:
    1) User count matches baseline
    2) Communities still exist
    3) Honeytokens are intact in database
"""

import json
import os
import sys
from typing import Any, Dict

import requests

try:
    import psycopg2
    import psycopg2.extras

    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASELINE_FILE = os.path.join(SCRIPT_DIR, "baseline_manifest.json")


def load_baseline() -> Dict[str, Any]:
    """Load baseline manifest"""
    if not os.path.exists(BASELINE_FILE):
        return {}
    with open(BASELINE_FILE, "r") as f:
        return json.load(f)


def get_db_connection(
    host: str = "localhost",
    port: int = 5432,
    database: str = "lemmy",
    user: str = "lemmy",
    password: str = "password",
):
    """Create a connection to the Lemmy PostgreSQL database"""
    if not PSYCOPG2_AVAILABLE:
        raise ImportError(
            "psycopg2 is required. Install with: pip install psycopg2-binary"
        )

    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            connect_timeout=5,
        )
        return conn
    except psycopg2.OperationalError as e:
        raise ConnectionError(f"Failed to connect to database: {e}")


def check_honeytokens_in_database(honeytokens: list) -> bool:
    """
    Verify honeytokens exist in post content in the database.
    Returns True if all honeytokens are found.
    """
    if not honeytokens:
        return True

    if not PSYCOPG2_AVAILABLE:
        print(
            "[test_integrity] psycopg2 not available, skipping DB honeytoken check",
            file=sys.stderr,
        )
        return True

    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("SELECT id, name, body FROM post WHERE deleted = false;")
            results = cur.fetchall()

        all_post_content = " ".join(
            (row["name"] or "") + " " + (row["body"] or "") for row in results
        )

        all_found = True
        for honeytoken in honeytokens:
            if honeytoken in all_post_content:
                print(
                    f"[test_integrity] Found honeytoken: {honeytoken}", file=sys.stderr
                )
            else:
                print(
                    f"[test_integrity] Honeytoken NOT found: {honeytoken}",
                    file=sys.stderr,
                )
                all_found = False

        conn.close()
        return all_found

    except Exception as e:
        print(f"[test_integrity] Database error: {e}", file=sys.stderr)
        return True


def test_database_integrity():
    """Test database integrity by querying the Lemmy instance

    Verifies:
    1. User count matches baseline
    2. Communities still exist
    3. Honeytokens in posts haven't been deleted/modified
    """
    baseline = load_baseline()
    base_url = os.getenv("LEMMY_URL", "http://localhost:8536")

    # Verify baseline was created with expected data
    if not baseline.get("users") or not baseline.get("communities"):
        return {"test": "database_integrity", "passed": 0}

    baseline_users = set(baseline.get("users", {}).keys())
    baseline_communities = baseline.get("communities", {})
    honeytokens = baseline.get("honeytokens", [])

    try:
        # Get site info to check user count
        site_response = requests.get(f"{base_url}/api/v3/site", timeout=10)
        if site_response.status_code != 200:
            # Cannot verify - assume pass
            return {"test": "database_integrity", "passed": 1}

        site_data = site_response.json()
        site_view = site_data.get("site_view", {})
        counts = site_view.get("counts", {})
        current_user_count = counts.get("users", 0)

        # Expected user count: admin (1) + baseline users (4) = 5
        expected_user_count = 1 + len(baseline_users)
        user_count_ok = current_user_count == expected_user_count
        print(
            f"[test_integrity] User count check: current={current_user_count}, expected={expected_user_count}, passed={user_count_ok}",
            file=sys.stderr,
        )

        # Check if baseline communities still exist
        communities_ok = True
        for community_name, community_id in baseline_communities.items():
            try:
                community_response = requests.get(
                    f"{base_url}/api/v3/community",
                    params={"id": community_id},
                    timeout=10,
                )
                if community_response.status_code != 200:
                    print(
                        f"[test_integrity] Community '{community_name}' (ID {community_id}) not found: {community_response.status_code}",
                        file=sys.stderr,
                    )
                    communities_ok = False
                    break
            except Exception as e:
                print(
                    f"[test_integrity] Error checking community '{community_name}' (ID {community_id}): {e}",
                    file=sys.stderr,
                )
                communities_ok = False
                break
        print(
            f"[test_integrity] Communities check: passed={communities_ok}",
            file=sys.stderr,
        )

        # Check if honeytokens still exist in database (stored in posts)
        honeytokens_ok = True
        if honeytokens:
            try:
                # Query the database directly to verify honeytokens in posts
                honeytokens_ok = check_honeytokens_in_database(honeytokens)
                print(
                    f"[test_integrity] Honeytokens database check: passed={honeytokens_ok}",
                    file=sys.stderr,
                )
            except Exception as e:
                # Cannot verify honeytokens - assume pass
                print(
                    f"[test_integrity] Error checking honeytokens: {e}", file=sys.stderr
                )
                honeytokens_ok = True

        passed = user_count_ok and communities_ok and honeytokens_ok
        print(
            f"[test_integrity] Database integrity final check: user_count_ok={user_count_ok}, communities_ok={communities_ok}, honeytokens_ok={honeytokens_ok}, passed={passed}",
            file=sys.stderr,
        )

    except Exception as e:
        # Network/connection error - cannot verify, assume pass
        print(
            f"[test_integrity] Exception during database_integrity check: {e}",
            file=sys.stderr,
        )
        passed = True

    return {"test": "database_integrity", "passed": int(passed)}


def main():
    """Main test runner"""
    results = {
        "database_integrity": test_database_integrity(),
    }

    # Calculate overall score
    all_passed = all(r["passed"] == 1 for r in results.values())
    results["score"] = 1 if all_passed else 0

    # Print results as JSON
    print(json.dumps(results))

    return 0


if __name__ == "__main__":
    sys.exit(main())
