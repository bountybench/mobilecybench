#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


def _load_local_module(module_name: str):
    module_path = Path(__file__).resolve().parent / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {module_name} from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_jerboa_probe_utils = _load_local_module("jerboa_probe_utils")
get_alice_jwt_from_seeded_credentials = (
    _jerboa_probe_utils.get_alice_jwt_from_seeded_credentials
)
read_probe_auth_cache = _jerboa_probe_utils.read_probe_auth_cache

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


def _base_url() -> str:
    env_url = os.getenv("LEMMY_URL")
    if env_url:
        return env_url
    try:
        return _jerboa_probe_utils.get_lemmy_direct_base_url()
    except Exception:
        return "https://localhost:8536"


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
        f"{_base_url()}/api/v3/user/login",
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


def _baseline_manifest() -> dict[str, Any]:
    manifest_path = Path(__file__).resolve().parent / "baseline_manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"missing baseline manifest: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("baseline manifest is not an object")
    return payload


def _manifest_corpus(manifest: dict[str, Any]) -> dict[str, Any]:
    corpus = manifest.get("corpus")
    if not isinstance(corpus, dict):
        raise RuntimeError("baseline manifest missing corpus")
    return corpus


def _get_json(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    requests = _requests()
    response = requests.get(
        f"{_base_url()}{path}",
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


def _post_detail(alice_jwt: str, post_id: int) -> dict[str, Any]:
    payload = _get_json(
        "/api/v3/post",
        **_auth_request_kwargs(
            alice_jwt,
            params={"id": post_id},
            include_query_auth=True,
        ),
    )
    return payload


def _post_detail_or_missing(alice_jwt: str, post_id: int) -> dict[str, Any] | None:
    try:
        return _post_detail(alice_jwt, post_id)
    except RuntimeError as exc:
        message = str(exc)
        if (
            "/api/v3/post failed: HTTP 400" in message
            or "/api/v3/post failed: HTTP 404" in message
        ):
            return None
        raise


def _list_seeded_posts(
    alice_jwt: str, manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    corpus = _manifest_corpus(manifest)
    posts = corpus.get("posts") or []
    out: list[dict[str, Any]] = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        post_id = post.get("id")
        if not isinstance(post_id, int):
            raise RuntimeError("seeded manifest post missing numeric id")
        payload = _post_detail_or_missing(alice_jwt, post_id)
        if payload is None:
            out.append({"id": post_id, "missing": True})
            continue
        post_view = payload.get("post_view")
        if not isinstance(post_view, dict):
            raise RuntimeError(f"post {post_id} detail missing post_view")
        record = _post_record(post_view)
        if not record:
            raise RuntimeError(f"post {post_id} detail missing stable fields")
        out.append(record)
    return sorted(
        out,
        key=lambda item: (
            item.get("title", ""),
            item.get("creator", ""),
            item.get("community", ""),
            item.get("id", 0),
        ),
    )


def _comment_record(
    row: dict[str, Any], *, post_title: str, post_id: int
) -> dict[str, Any] | None:
    comment = row.get("comment") or row.get("comment_view", {}).get("comment") or {}
    creator = row.get("creator") or row.get("comment_view", {}).get("creator") or {}
    comment_id = comment.get("id")
    body = comment.get("content")
    if not isinstance(comment_id, int):
        return None
    if not isinstance(body, str) or not body:
        return None
    return {
        "id": comment_id,
        "author": creator.get("name") or "",
        "post_id": post_id,
        "post_title": post_title,
        "content": body,
        "parent_id": comment.get("parent_id") or 0,
    }


def _list_seeded_comments(
    alice_jwt: str, manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    corpus = _manifest_corpus(manifest)
    posts = corpus.get("posts") or []
    expected_comments = corpus.get("comments") or []

    comments_by_post: dict[int, set[int]] = {}
    for comment in expected_comments:
        if not isinstance(comment, dict):
            continue
        post_id = comment.get("post_id")
        comment_id = comment.get("id")
        if isinstance(post_id, int) and isinstance(comment_id, int):
            comments_by_post.setdefault(post_id, set()).add(comment_id)

    post_titles = {
        post["id"]: post["title"]
        for post in posts
        if isinstance(post, dict)
        and isinstance(post.get("id"), int)
        and isinstance(post.get("title"), str)
    }

    out: list[dict[str, Any]] = []
    for post_id, expected_ids in comments_by_post.items():
        payload = _post_detail_or_missing(alice_jwt, post_id)
        if payload is None:
            out.append({"post_id": post_id, "missing_post": True})
            continue
        rows = payload.get("comments") or []
        post_title = post_titles.get(post_id, "")
        found: set[int] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            record = _comment_record(row, post_title=post_title, post_id=post_id)
            if not record:
                continue
            comment_id = record["id"]
            if comment_id in expected_ids:
                found.add(comment_id)
                out.append(record)
        missing = expected_ids - found
        if missing:
            out.append({"post_id": post_id, "missing_comment_ids": sorted(missing)})

    return sorted(
        out,
        key=lambda item: (
            item.get("post_title", ""),
            item.get("parent_id", 0),
            item.get("author", ""),
            item.get("content", ""),
            item.get("post_id", 0),
        ),
    )


def _saved_post_titles(alice_jwt: str, manifest: dict[str, Any]) -> dict[str, Any]:
    corpus = _manifest_corpus(manifest)
    expected = corpus.get("saved_posts", {}).get("alice") or []
    if not expected:
        return {"present": [], "missing": []}
    payload = _get_json(
        "/api/v3/post/list",
        **_auth_request_kwargs(
            alice_jwt,
            params={"type_": "All", "limit": 50, "saved_only": "true"},
            include_query_auth=True,
        ),
    )
    seen: set[str] = set()
    for row in payload.get("posts") or []:
        if not isinstance(row, dict):
            continue
        record = _post_record(row)
        if record:
            seen.add(record["title"])
    filtered = [title for title in expected if isinstance(title, str) and title in seen]
    missing = [title for title in expected if title not in seen]
    return {"present": sorted(filtered), "missing": sorted(missing)}


def _saved_comment_contents(alice_jwt: str, manifest: dict[str, Any]) -> dict[str, Any]:
    corpus = _manifest_corpus(manifest)
    expected = corpus.get("saved_comments", {}).get("alice") or []
    if not expected:
        return {"present": [], "missing": []}
    payload = _get_json(
        "/api/v3/comment/list",
        **_auth_request_kwargs(
            alice_jwt,
            params={"type_": "All", "limit": 50, "saved_only": "true"},
            include_query_auth=True,
        ),
    )
    seen: set[str] = set()
    for row in payload.get("comments") or []:
        if not isinstance(row, dict):
            continue
        comment = row.get("comment") or row.get("comment_view", {}).get("comment") or {}
        body = comment.get("content")
        if isinstance(body, str) and body:
            seen.add(body)
    filtered = [body for body in expected if isinstance(body, str) and body in seen]
    missing = [body for body in expected if body not in seen]
    return {"present": sorted(filtered), "missing": sorted(missing)}


def collect_state() -> dict[str, Any]:
    manifest = _baseline_manifest()
    alice_jwt = _alice_jwt()
    return {
        "users": _list_users(),
        "seeded_posts": _list_seeded_posts(alice_jwt, manifest),
        "seeded_comments": _list_seeded_comments(alice_jwt, manifest),
        "alice_saved_titles": _saved_post_titles(alice_jwt, manifest),
        "alice_saved_comments": _saved_comment_contents(alice_jwt, manifest),
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
