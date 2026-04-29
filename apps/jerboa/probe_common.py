#!/usr/bin/env python3
"""
Shared probe helpers for Jerboa.

Keeps CA setup, JSON extraction, and post/private-message body parsing in one
place so the malicious_app and remote_attacker probe sets stay aligned.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


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
    victim_jwt: str,
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
        params={"type_": "All", "limit": 200},
        headers={"Authorization": f"Bearer {victim_jwt}"},
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
            params={"type_": "All", "limit": 200, "saved_only": "true"},
            headers={"Authorization": f"Bearer {victim_jwt}"},
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
            params={"id": post["id"], "auth": victim_jwt},
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
