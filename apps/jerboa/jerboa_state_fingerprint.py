#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any

from jerboa_probe_utils import (
    get_alice_jwt_from_seeded_credentials,
    read_probe_auth_cache,
)

LEMMY_BASE_URL = os.getenv("LEMMY_URL", "https://localhost:8536")
EXPECTED_USERS = ("admin", "agent", "alice", "bob", "charlie")


def _verify_value() -> str | bool:
    ca_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "tls",
        "rootCA.pem",
    )
    override = os.getenv("REQUESTS_CA_BUNDLE")
    if override:
        return override
    return ca_path if os.path.exists(ca_path) else True


def _requests():
    import requests

    return requests


def _admin_jwt() -> str:
    cache = read_probe_auth_cache()
    token = cache.get("admin_jwt")
    if isinstance(token, str) and token:
        return token
    secrets_path = os.path.join(os.path.dirname(__file__), "secrets.json")
    try:
        with open(secrets_path, "r", encoding="utf-8") as handle:
            secrets = json.load(handle)
    except Exception as exc:
        raise RuntimeError(f"missing admin_jwt in probe auth cache: {exc}") from exc

    password = secrets.get("admin_password")
    if not isinstance(password, str) or not password:
        raise RuntimeError("missing admin_password for admin JWT fallback")

    requests = _requests()
    response = requests.post(
        f"{LEMMY_BASE_URL}/api/v3/user/login",
        json={"username_or_email": "admin", "password": password},
        timeout=15,
        verify=_verify_value(),
    )
    if response.status_code != 200:
        raise RuntimeError(f"admin login failed: HTTP {response.status_code}")
    payload = response.json()
    token = payload.get("jwt") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError("admin login returned no JWT")
    return token


def _alice_jwt() -> str:
    token = get_alice_jwt_from_seeded_credentials()
    if token:
        return token
    raise RuntimeError("missing alice_jwt")


def _get_json(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    requests = _requests()
    response = requests.get(
        f"{LEMMY_BASE_URL}{path}",
        params=params,
        headers=headers,
        timeout=15,
        verify=_verify_value(),
    )
    if response.status_code != 200:
        raise RuntimeError(f"{path} failed: HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} returned non-object payload")
    return payload


def _auth_request_kwargs(
    jwt: str,
    *,
    params: dict[str, Any] | None = None,
    include_query_auth: bool = False,
) -> dict[str, Any]:
    merged = dict(params or {})
    if include_query_auth:
        merged["auth"] = jwt
    return {
        "params": merged,
        "headers": {"Authorization": f"Bearer {jwt}"},
    }


def _list_users() -> list[dict[str, Any]]:
    admin_jwt = _admin_jwt()
    try:
        payload = _get_json(
            "/api/v3/user/list",
            **_auth_request_kwargs(admin_jwt, params={"limit": 50, "sort": "New"}),
        )
        rows = payload.get("users") or []
    except RuntimeError as exc:
        if "HTTP 404" not in str(exc):
            raise
        rows = []
        for username in EXPECTED_USERS:
            payload = _get_json(
                "/api/v3/user",
                **_auth_request_kwargs(
                    admin_jwt, params={"username": username}, include_query_auth=True
                ),
            )
            person_view = payload.get("person_view") or payload.get("user_view") or {}
            rows.append(person_view)
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        person = row.get("person") or {}
        name = person.get("name")
        if name not in EXPECTED_USERS:
            continue
        out.append(
            {
                "name": name,
                "banned": bool(person.get("banned")),
                "is_admin": bool(row.get("is_admin")),
            }
        )
    return sorted(out, key=lambda item: item["name"])


def _post_record(post_view: dict[str, Any]) -> dict[str, Any] | None:
    post = post_view.get("post") or post_view.get("post_view", {}).get("post") or {}
    creator = (
        post_view.get("creator") or post_view.get("post_view", {}).get("creator") or {}
    )
    community = (
        post_view.get("community")
        or post_view.get("post_view", {}).get("community")
        or {}
    )
    title = post.get("name")
    if not isinstance(title, str) or not title:
        return None
    post_id = post.get("id")
    if not isinstance(post_id, int):
        return None
    return {
        "id": post_id,
        "title": title,
        "body": post.get("body") or "",
        "url": post.get("url") or "",
        "creator": creator.get("name") or "",
        "community": community.get("name") or "",
    }


def _list_posts(alice_jwt: str, *, saved_only: bool = False) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"type_": "All", "limit": 50}
    if saved_only:
        params["saved_only"] = "true"
    payload = _get_json(
        "/api/v3/post/list", **_auth_request_kwargs(alice_jwt, params=params)
    )
    rows = payload.get("posts") or []
    if len(rows) >= 50:
        raise RuntimeError("post list reached limit 50; fingerprint would be truncated")
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        record = _post_record(row)
        if record:
            out.append(record)
    return sorted(
        out, key=lambda item: (item["title"], item["creator"], item["community"])
    )


def _list_comments(alice_jwt: str, posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    for post in posts:
        payload = _get_json(
            "/api/v3/comment/list",
            **_auth_request_kwargs(
                alice_jwt,
                params={"post_id": post["id"], "limit": 50, "sort": "New"},
            ),
        )
        rows = payload.get("comments") or []
        if len(rows) >= 50:
            raise RuntimeError(
                f"comment list for post {post['id']} reached limit 50; fingerprint would be truncated"
            )
        for row in rows:
            if not isinstance(row, dict):
                continue
            comment = (
                row.get("comment") or row.get("comment_view", {}).get("comment") or {}
            )
            creator = (
                row.get("creator") or row.get("comment_view", {}).get("creator") or {}
            )
            body = comment.get("content")
            if not isinstance(body, str) or not body:
                continue
            comments.append(
                {
                    "post_title": post["title"],
                    "creator": creator.get("name") or "",
                    "content": body,
                    "parent_id": comment.get("parent_id") or 0,
                }
            )
    return sorted(
        comments,
        key=lambda item: (
            item["post_title"],
            item["parent_id"],
            item["creator"],
            item["content"],
        ),
    )


def collect_state() -> dict[str, Any]:
    alice_jwt = _alice_jwt()
    posts = _list_posts(alice_jwt)
    return {
        "users": _list_users(),
        "posts": posts,
        "comments": _list_comments(alice_jwt, posts),
        "alice_saved_titles": [
            post["title"] for post in _list_posts(alice_jwt, saved_only=True)
        ],
    }


def fingerprint(state: dict[str, Any]) -> str:
    blob = json.dumps(
        state, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def current_baseline_fingerprint() -> str:
    return fingerprint(collect_state())


def main(argv: list[str]) -> int:
    state = collect_state()
    current = fingerprint(state)
    if len(argv) >= 2 and argv[1] == "fingerprint":
        print(current)
        return 0
    print(json.dumps({"fingerprint": current, "state": state}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
