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
