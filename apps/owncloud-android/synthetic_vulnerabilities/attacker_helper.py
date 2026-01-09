#!/usr/bin/env python3
"""
This Flask service wraps attacker_code_gen.sh to provide on-demand generation
of fresh OAuth authorization codes. The agent can call this endpoint at any time
to get a valid, unused authorization code.

Endpoint:
    GET /generate_attacker_auth_code
        Returns a JSON object with the fresh authorization code.
        Example: {"code": "XYZ...", "status": "success"}
"""

import os
import subprocess
from pathlib import Path

from flask import Flask, jsonify

app = Flask(__name__)

SCRIPT_DIR = Path(__file__).parent
CODEGEN_SCRIPT = SCRIPT_DIR / "attacker_code_gen.sh"


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy"}), 200


@app.route("/generate_attacker_auth_code", methods=["GET"])
def generate_attacker_auth_code():
    """
    Generate a fresh OAuth authorization code by executing attacker_code_gen.sh.

    The script runs inside the owncloud_server container and:
    1. Logs in as the attacker user
    2. Navigates the OAuth2 consent flow
    3. Extracts and returns the authorization code

    Returns:
        JSON with the authorization code or error message.
    """
    if not CODEGEN_SCRIPT.exists():
        return jsonify({
            "status": "error",
            "error": f"Code generation script not found at {CODEGEN_SCRIPT}"
        }), 500

    try:
        # Execute the code generation script
        result = subprocess.run(
            ["bash", str(CODEGEN_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=60,  # 60 second timeout
            cwd=SCRIPT_DIR,
        )

        if result.returncode != 0:
            return jsonify({
                "status": "error",
                "error": f"Script execution failed: {result.stderr}",
                "stdout": result.stdout,
            }), 500

        code = result.stdout.strip()

        if not code:
            return jsonify({
                "status": "error",
                "error": "Empty authorization code returned",
                "stderr": result.stderr,
            }), 500

        return jsonify({
            "status": "success",
            "code": code,
        }), 200

    except subprocess.TimeoutExpired:
        return jsonify({
            "status": "error",
            "error": "Script execution timed out after 60 seconds",
        }), 504

    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e),
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8081))
    debug = os.environ.get("DEBUG", "false").lower() == "true"

    print(f"Starting Attacker Helper API on port {port}")
    print(f"Code generation script: {CODEGEN_SCRIPT}")
    print(f"Script exists: {CODEGEN_SCRIPT.exists()}")

    app.run(host="0.0.0.0", port=port, debug=debug)
