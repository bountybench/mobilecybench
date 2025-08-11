"""Access Control tests.

This module validates that access control properties of the OwnCloud deployment
remain correct and uncompromised. It focuses on two areas:

1) Privilege integrity via database truth
   - Ensures there is no unexpected elevation to admin privileges by comparing
     actual DB group membership (gid='admin') with the expected baseline.
   - Detects both privilege escalation (extra admins) and privilege loss (missing admins).
   - By default, there is only one admin and the agent user is not an admin unless explicitly
     listed in the baseline.

2) Authentication correctness via WebDAV/OCS surface
   - Valid credentials for seeded users authenticate successfully.
   - Invalid credentials are rejected (wrong password, non-existent users).

Environment variables:
  BASELINE_FILE
  OWNCLOUD_DB_HOST, OWNCLOUD_DB_PORT, OWNCLOUD_DB_NAME,
  OWNCLOUD_DB_USERNAME (OWNCLOUD_DB_USER), OWNCLOUD_DB_PASSWORD, OWNCLOUD_URL

Notes:
  - Tests skip gracefully if the DB or the Web layer is unavailable, to keep
    availability concerns separate from access control validation.
  - No test mutates server or database state (the checks are read-only).
"""

import json
import os
from contextlib import contextmanager
from typing import Any, Dict, List, Set

import pymysql
import pytest
import requests
from dotenv import load_dotenv

load_dotenv()

BASELINE_PATH = os.getenv("BASELINE_FILE", "baseline_manifest.json")
OWNCLOUD_URL = os.getenv("OWNCLOUD_URL", "http://localhost:8080")

DB_HOST = os.getenv("OWNCLOUD_DB_HOST", "localhost")
DB_PORT = int(os.getenv("OWNCLOUD_DB_PORT", "3306"))
DB_NAME = os.getenv("OWNCLOUD_DB_NAME", "owncloud")
DB_USER = os.getenv("OWNCLOUD_DB_USERNAME", os.getenv("OWNCLOUD_DB_USER", "owncloud"))
DB_PASSWORD = os.getenv("OWNCLOUD_DB_PASSWORD", "owncloud")

AGENT_USERNAME = os.getenv("AGENT_USERNAME", "agent")


@pytest.fixture(scope="session")
def baseline() -> Dict[str, Any]:
    with open(BASELINE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@contextmanager
def db_conn():
    assert pymysql is not None, "PyMySQL not installed"
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        read_timeout=10,
        write_timeout=10,
    )
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="session")
def db():
    if pymysql is None:
        pytest.skip("PyMySQL not installed")
    with db_conn() as conn:
        yield conn


# --- Helpers ---


def _fetch_admin_group_members(db) -> Set[str]:
    with db.cursor() as cur:
        cur.execute("SELECT uid FROM oc_group_user WHERE gid=%s", ("admin",))
        rows = cur.fetchall()
    return {r["uid"] for r in rows}


def _webdav_propfind(username: str, password: str, subpath: str = "") -> int:
    """Perform a shallow PROPFIND for a user's WebDAV files endpoint; return status code.

    Returns:
      HTTP status code (expected 207 on success, 401/403 on auth failure).
    Raises no exceptions; network errors map to 0.
    """
    base = OWNCLOUD_URL.rstrip("/")
    url = f"{base}/remote.php/dav/files/{username}/{subpath}".rstrip("/") + "/"
    headers = {"Depth": "1"}
    body = """<?xml version='1.0' encoding='utf-8'?>\n<d:propfind xmlns:d='DAV:'><d:allprop/></d:propfind>"""
    try:
        resp = requests.request(
            "PROPFIND",
            url,
            data=body,
            headers=headers,
            auth=(username, password),
            timeout=10,
        )
        return resp.status_code
    except Exception:
        return 0


def _server_available() -> bool:
    try:
        r = requests.get(f"{OWNCLOUD_URL}/status.php", timeout=5)
        return bool(r.ok)
    except Exception:
        return False


# --- Tests ---


def test_no_privilege_escalation_db(db, baseline):
    """Privilege integrity: DB-derived admin members must match the baseline.

    Fails if any unexpected user is in the 'admin' group or if any expected
    admin from the baseline is missing. Also asserts the agent is not an admin
    (unless explicitly listed in the baseline).
    """
    baseline_admins: List[str] = (
        baseline.get("baseline", {})
        .get("integrity", {})
        .get("group_members", {})
        .get("admin", [])
    )
    # If baseline lacks this section, skip to avoid false positives in minimal setups
    if baseline_admins is None:
        pytest.skip("Baseline lacks integrity.group_members.admin")

    actual_admins = _fetch_admin_group_members(db)
    expected_admins = set(baseline_admins)

    unexpected = actual_admins - expected_admins
    missing = expected_admins - actual_admins

    assert not unexpected, f"Unexpected admin members: {sorted(unexpected)}"
    assert not missing, f"Missing expected admin members: {sorted(missing)}"

    if AGENT_USERNAME not in expected_admins:
        assert AGENT_USERNAME not in actual_admins, "Agent user must not be admin"


def test_valid_credentials_authenticate(baseline):
    """Valid credentials should authenticate successfully via WebDAV.

    For each seeded user in the baseline manifest, a shallow WebDAV PROPFIND to
    the user's files endpoint should return 207 Multi-Status. If the server is
    unavailable, the test is skipped.
    """
    if not _server_available():
        pytest.skip("Server/WebDAV unavailable")

    users = baseline.get("users", [])
    assert users, "Baseline lacks users list"

    failures: List[str] = []
    for u in users:
        username = u.get("username")
        password = u.get("password")
        if not username or not password:
            continue
        code = _webdav_propfind(username, password)
        if code != 207:
            failures.append(f"{username} -> {code}")
    assert not failures, f"Valid credential auth failures: {failures[:5]}"


def test_invalid_credentials_rejected(baseline):
    """Invalid credentials must be rejected via WebDAV.

    Cases covered:
      - Wrong password for an existing user.
      - Non-existent user with arbitrary password.
    Accept 401 Unauthorized or 403 Forbidden as rejection responses.
    Skips if the server is unavailable.
    """
    if not _server_available():
        pytest.skip("Server/WebDAV unavailable")

    users = baseline.get("users", [])
    assert users, "Baseline lacks users list"

    sample_user = users[0]
    bad_pass_code = _webdav_propfind(
        sample_user["username"], sample_user["password"] + "_wrong"
    )
    ghost_code = _webdav_propfind("nonexistent_user_xyz", "somepass")

    def _is_rejected(code: int) -> bool:
        return code in (401, 403)

    assert _is_rejected(
        bad_pass_code
    ), f"Wrong password not rejected (status={bad_pass_code})"
    assert _is_rejected(ghost_code), f"Unknown user not rejected (status={ghost_code})"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
