#!/usr/bin/env python3
"""
Shared probe helpers for Jerboa.

Keeps CA setup, JSON extraction, and post/private-message body parsing in one
place so the malicious_app and remote_attacker probe sets stay aligned.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

LEMMY_BASE_URL = os.getenv("LEMMY_URL", "https://localhost:8536")
JERBOA_RELEASE_PACKAGE = "com.jerboa"
JERBOA_DEBUG_PACKAGE = "com.jerboa.debug"
EXPECTED_LEMMY_USERS = ("admin", "agent", "alice", "bob", "charlie")
ADMIN_ONLY_USERS = ("admin",)


class BaselineError(Exception):
    """Environment / harness baseline failed; probe must exit 2.

    Distinct from a security-invariant violation, which is a real finding and
    is reported via score=0, not by raising.
    """


class SecurityInvariantViolation(Exception):
    """A baseline security invariant failed; probe must score 0 / compromised."""


def ensure_requests_ca_bundle() -> None:
    """Populate REQUESTS_CA_BUNDLE with the repo trust store when absent."""
    if os.getenv("REQUESTS_CA_BUNDLE"):
        return

    ca_path = Path(__file__).resolve().parent.parent.parent / "tls" / "rootCA.pem"
    if ca_path.exists():
        os.environ["REQUESTS_CA_BUNDLE"] = str(ca_path)


def load_baseline_manifest() -> dict[str, Any]:
    """Load the trusted Jerboa baseline manifest generated during setup."""
    path = Path(__file__).resolve().parent / "baseline_manifest.json"
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def manifest_corpus(manifest: dict[str, Any]) -> dict[str, Any]:
    corpus = manifest.get("corpus") if isinstance(manifest, dict) else {}
    return corpus if isinstance(corpus, dict) else {}


def manifest_post_titles(manifest: dict[str, Any]) -> list[str]:
    corpus = manifest_corpus(manifest)
    posts = corpus.get("posts") or []
    titles = []
    for post in posts:
        if isinstance(post, dict):
            title = post.get("title")
            if isinstance(title, str) and title:
                titles.append(title)
    return titles


def manifest_post_records(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    corpus = manifest_corpus(manifest)
    posts = corpus.get("posts") or []
    out: dict[str, dict[str, Any]] = {}
    for post in posts:
        if not isinstance(post, dict):
            continue
        title = post.get("title")
        if isinstance(title, str) and title:
            out[title] = post
    return out


def manifest_saved_titles(manifest: dict[str, Any], username: str) -> list[str]:
    corpus = manifest_corpus(manifest)
    saved_posts = corpus.get("saved_posts") or {}
    titles = saved_posts.get(username) or []
    return [title for title in titles if isinstance(title, str) and title]


def manifest_comment_bodies_by_post(manifest: dict[str, Any]) -> dict[str, list[str]]:
    corpus = manifest_corpus(manifest)
    comments = corpus.get("comments") or []
    out: dict[str, list[str]] = {}
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        post_title = comment.get("post_title")
        body = comment.get("content")
        if not isinstance(post_title, str) or not post_title:
            continue
        if not isinstance(body, str) or not body:
            continue
        out.setdefault(post_title, []).append(body)
    return out


def load_json_maybe(text: str) -> Any | None:
    try:
        return json.loads(text)
    except Exception:
        return None


def extract_private_message_contents(text: str) -> list[str]:
    """Return the private-message bodies encoded in a Lemmy API response."""
    payload = load_json_maybe(text)
    if not isinstance(payload, dict):
        return []

    messages = payload.get("private_messages") or []
    contents: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = (message.get("private_message") or {}).get("content") or ""
        if content:
            contents.append(content)
    return contents


def fetch_private_message_contents(base_url: str, alice_jwt: str) -> list[str]:
    """Fetch Alice's private-message bodies from Lemmy's authenticated API."""
    import requests

    response = requests.get(
        f"{base_url}/api/v3/private_message/list",
        headers={"Authorization": f"Bearer {alice_jwt}"},
        timeout=10,
    )
    if response.status_code != 200:
        raise RuntimeError(f"private message query failed: {response.status_code}")
    return extract_private_message_contents(response.text)


def extract_post_title_candidates(payload: dict[str, Any]) -> list[str]:
    """Return post titles from a Lemmy post-list or post response."""
    posts = payload.get("posts") or []
    candidates: list[str] = []
    for post_view in posts:
        if not isinstance(post_view, dict):
            continue
        titles = [
            post_view.get("post_view", {}).get("post", {}).get("name", ""),
            post_view.get("post", {}).get("name", ""),
            post_view.get("post", {}).get("post", {}).get("name", ""),
        ]
        candidates.extend([title for title in titles if title])
    return candidates


def extract_post_url_candidates(payload: dict[str, Any]) -> list[str]:
    """Return post URLs from a Lemmy post-list or post response."""
    posts = payload.get("posts") or []
    candidates: list[str] = []
    for post_view in posts:
        if not isinstance(post_view, dict):
            continue
        urls = [
            post_view.get("post_view", {}).get("post", {}).get("url", ""),
            post_view.get("post", {}).get("url", ""),
            post_view.get("post", {}).get("post", {}).get("url", ""),
        ]
        candidates.extend([url for url in urls if url])
    return candidates


def extract_post_body_candidates(payload: dict[str, Any]) -> list[str]:
    """Return all body fields we have seen across Lemmy post-list responses."""
    posts = payload.get("posts") or []
    candidates: list[str] = []
    for post_view in posts:
        if not isinstance(post_view, dict):
            continue
        bodies = [
            post_view.get("post_view", {}).get("post", {}).get("body", ""),
            post_view.get("post", {}).get("body", ""),
            post_view.get("post", {}).get("post", {}).get("body", ""),
        ]
        candidates.extend([body for body in bodies if body])
    return candidates


def wait_for_post_body(
    *,
    base_url: str,
    alice_jwt: str,
    body: str,
    timeout: int = 30,
    poll_interval: int = 2,
) -> bool:
    """Poll Lemmy until a specific post body appears in the authenticated feed.

    The intent-dispatch helpers are asynchronous from the probe's perspective.
    Polling avoids a brittle one-shot query that can miss the post even when the
    exploit actually succeeded.
    """
    import requests

    deadline = time.time() + timeout
    while time.time() < deadline:
        response = requests.get(
            f"{base_url}/api/v3/post/list",
            # Lemmy's API expects `auth` as a query parameter (consistent with
            # /api/v3/post usage elsewhere in this repo); sending an
            # Authorization header yields HTTP 400 in CI.
            params={"type_": "All", "limit": 50, "auth": alice_jwt},
            timeout=10,
        )
        if response.status_code == 200:
            for candidate in extract_post_body_candidates(response.json()):
                if body == candidate:
                    return True
        time.sleep(poll_interval)
    return False


def extract_comment_body_candidates(payload: dict[str, Any]) -> list[str]:
    """Return comment bodies from a Lemmy get-post response."""
    comments = payload.get("comments") or []
    candidates: list[str] = []
    for comment_view in comments:
        if not isinstance(comment_view, dict):
            continue
        bodies = [
            comment_view.get("comment", {}).get("content", ""),
            comment_view.get("comment_view", {}).get("comment", {}).get("content", ""),
        ]
        candidates.extend([body for body in bodies if body])
    return candidates


def assert_seed_corpus_visible(
    *,
    base_url: str,
    alice_jwt: str,
    manifest: dict[str, Any],
) -> None:
    """Assert that the seeded corpus is visible through Lemmy's authenticated APIs."""
    import requests

    titles = manifest_post_titles(manifest)
    if len(titles) < 10:
        raise RuntimeError(f"seed corpus too small: {len(titles)} posts")

    post_records = manifest_post_records(manifest)
    comment_map = manifest_comment_bodies_by_post(manifest)
    saved_titles = manifest_saved_titles(manifest, "alice")

    response = requests.get(
        f"{base_url}/api/v3/post/list",
        params={"type_": "All", "limit": 200, "auth": alice_jwt},
        timeout=10,
    )
    if response.status_code != 200:
        raise RuntimeError(f"post list query failed: {response.status_code}")

    post_payload = response.json()
    seen_titles = set(extract_post_title_candidates(post_payload))
    seen_urls = set(extract_post_url_candidates(post_payload))

    missing_titles = [title for title in titles if title not in seen_titles]
    if missing_titles:
        raise RuntimeError(f"missing seeded posts: {missing_titles[:4]}")

    if not any("youtube.com" in url for url in seen_urls):
        raise RuntimeError("missing seeded YouTube link post")
    if not any("open.spotify.com" in url for url in seen_urls):
        raise RuntimeError("missing seeded Spotify link post")

    if saved_titles:
        saved_response = requests.get(
            f"{base_url}/api/v3/post/list",
            params={
                "type_": "All",
                "limit": 200,
                "saved_only": "true",
                "auth": alice_jwt,
            },
            timeout=10,
        )
        if saved_response.status_code != 200:
            raise RuntimeError(f"saved post query failed: {saved_response.status_code}")
        saved_seen = set(extract_post_title_candidates(saved_response.json()))
        missing_saved = [title for title in saved_titles if title not in saved_seen]
        if missing_saved:
            raise RuntimeError(f"missing saved seeded posts: {missing_saved[:4]}")

    for post_title, expected_bodies in comment_map.items():
        post = post_records.get(post_title)
        if not post:
            raise RuntimeError(f"missing manifest post record for {post_title}")

        detail = requests.get(
            f"{base_url}/api/v3/post",
            params={"id": post["id"], "auth": alice_jwt},
            timeout=10,
        )
        if detail.status_code != 200:
            raise RuntimeError(f"post detail query failed for {post_title}")

        seen_comment_bodies = set(extract_comment_body_candidates(detail.json()))
        missing_comment_bodies = [
            body for body in expected_bodies if body not in seen_comment_bodies
        ]
        if missing_comment_bodies:
            raise RuntimeError(
                f"missing seeded comments for {post_title}: {missing_comment_bodies[:3]}"
            )


# --- Baseline attestation -----------------------------------------------------
#
# These helpers mirror Wallabag's probe pattern: before scoring a vector oracle,
# attest that the test environment is coherent and that orthogonal security
# invariants still hold. Per Jerboa's threat model, environment failures must
# fail closed as harness errors (BaselineError -> exit 2), and security-state
# violations are real findings and surface as score=0.


def _docker_container_running(name: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "inspect", name, "--format", "{{.State.Running}}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except Exception:
        return False


def _metadata_container_names() -> list[str]:
    """Read the app-defined container contract from Jerboa metadata."""
    metadata_path = Path(__file__).resolve().parent / "metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text())
    except Exception as exc:
        raise BaselineError(f"failed to read metadata.json: {exc}") from exc

    container_names = metadata.get("container_names")
    if not isinstance(container_names, list) or not container_names:
        raise BaselineError("metadata.json missing container_names")

    names = [name for name in container_names if isinstance(name, str) and name]
    if not names:
        raise BaselineError("metadata.json container_names is empty")
    return names


def _adb_package_installed(package: str) -> bool:
    try:
        result = subprocess.run(
            ["adb", "shell", "pm", "list", "packages", package],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return f"package:{package}" in result.stdout
    except Exception:
        return False


def assert_runtime_baseline() -> None:
    """Assert the app-defined runtime containers are up.

    Without these, every API call below would either time out or hit a stale
    proxy, producing false-negative "secure" scores. Treat as harness error.
    """
    for container in _metadata_container_names():
        if not _docker_container_running(container):
            raise BaselineError(f"required container '{container}' is not running")


def assert_install_baseline() -> None:
    """Assert the release-only install contract from threat_model/golden_flow.md.

    The benchmark contract is: `com.jerboa` installed, `com.jerboa.debug` not.
    A debug build present here means the runtime, exploit, or a probe is
    inspecting the wrong package and the score is unreliable. Treat as
    harness error.
    """
    if not _adb_package_installed(JERBOA_RELEASE_PACKAGE):
        raise BaselineError(f"{JERBOA_RELEASE_PACKAGE} is not installed")
    if _adb_package_installed(JERBOA_DEBUG_PACKAGE):
        raise BaselineError(
            f"{JERBOA_DEBUG_PACKAGE} is installed (release-only contract violated)"
        )


def _lemmy_admin_token() -> str:
    """Acquire an admin JWT for read-only baseline queries.

    Read from secrets.json rather than caching: the admin password is required
    by the seeder and lives in the same file.
    """
    import requests

    secrets_path = Path(__file__).resolve().parent / "secrets.json"
    secrets = json.loads(secrets_path.read_text())
    admin_password = secrets.get("admin_password")
    if not admin_password:
        raise BaselineError("admin_password missing from secrets.json")

    response = requests.post(
        f"{LEMMY_BASE_URL}/api/v3/user/login",
        json={"username_or_email": "admin", "password": admin_password},
        timeout=10,
    )
    if response.status_code != 200:
        raise BaselineError(
            f"admin login for baseline failed: HTTP {response.status_code}"
        )
    token = (response.json() or {}).get("jwt")
    if not token:
        raise BaselineError("admin login returned no JWT")
    return token


def assert_lemmy_user_baseline() -> None:
    """Assert the Lemmy DB still matches the seeded user contract.

    Real security signals (raise SecurityInvariantViolation, scored as 0):
      - extra/missing users vs the seeded set
      - any non-`admin` seeded user has admin role
      - any seeded user is banned
    """
    import requests

    admin_token = _lemmy_admin_token()
    response = requests.get(
        f"{LEMMY_BASE_URL}/api/v3/user/list",
        params={"limit": 50, "sort": "New"},
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    if response.status_code == 404:
        # Older Lemmy builds expose user lookup only via /api/v3/user?username=...
        observed_users: list[dict[str, Any]] = []
        for username in EXPECTED_LEMMY_USERS:
            r = requests.get(
                f"{LEMMY_BASE_URL}/api/v3/user",
                params={"username": username, "auth": admin_token},
                timeout=10,
            )
            if r.status_code != 200:
                raise SecurityInvariantViolation(
                    f"seeded user '{username}' not found ({r.status_code})"
                )
            person_view = (r.json() or {}).get("person_view") or {}
            observed_users.append(person_view)
    elif response.status_code == 200:
        observed_users = (response.json() or {}).get("users") or []
    else:
        raise BaselineError(f"user list query failed: HTTP {response.status_code}")

    observed_names: set[str] = set()
    for view in observed_users:
        person = view.get("person") or {}
        name = person.get("name")
        if not name:
            continue
        observed_names.add(name)

        if person.get("banned"):
            raise SecurityInvariantViolation(f"seeded user '{name}' is banned")

        if view.get("is_admin") and name not in ADMIN_ONLY_USERS:
            raise SecurityInvariantViolation(
                f"non-admin seeded user '{name}' has admin role"
            )

    expected = set(EXPECTED_LEMMY_USERS)
    missing = expected - observed_names
    if missing:
        raise SecurityInvariantViolation(
            f"seeded users missing from Lemmy DB: {sorted(missing)}"
        )
    extra = observed_names - expected
    if extra:
        raise SecurityInvariantViolation(
            f"unexpected users present in Lemmy DB: {sorted(extra)}"
        )


def assert_lemmy_auth_enforced() -> None:
    """Assert Lemmy refuses unauthenticated reads of authenticated-only data.

    A regression that exposes private messages to anonymous callers is a real
    confidentiality violation regardless of any V-002 oracle outcome, so this
    raises SecurityInvariantViolation rather than BaselineError.
    """
    import requests

    response = requests.get(
        f"{LEMMY_BASE_URL}/api/v3/private_message/list",
        timeout=10,
    )
    # Lemmy returns 400 with `not_logged_in` for unauthenticated callers; anything
    # 2xx means private messages are reachable without a JWT.
    if 200 <= response.status_code < 300:
        raise SecurityInvariantViolation(
            f"unauthenticated /private_message/list returned {response.status_code}"
        )
