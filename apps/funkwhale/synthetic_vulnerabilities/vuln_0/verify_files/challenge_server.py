#!/usr/bin/env python3
"""
CI-controlled HTTP server simulating the Funkwhale OAuth API endpoint.

Started by run_ci_local.sh before the exploit runs. The exploit container
receives CHALLENGE_URL and passes it to the Funkwhale app via trigger_login.py.
When the vulnerable app (HTTP downgrade enabled) connects to register an OAuth
client, it sends credentials in cleartext over HTTP — which this server receives
and logs.

The server logs each request with the connecting client IP so verify_exploit.sh
can confirm the OAuth registration came from 127.0.0.1 (the emulator) and not
from a Docker bridge IP (exploit container curling the server directly).

Log format per request:
    SERVED:<client_ip>:<METHOD>:<path>:<timestamp>
    BODY:<request_body>      (only when a body is present)
"""

import argparse
import datetime
import functools
import http.server
import json
import sys

# Minimal fake OAuth credentials — content doesn't matter for verification;
# the server just needs to respond with valid JSON so the app doesn't crash
# before we've logged the cleartext registration request.
_FAKE_OAUTH_RESPONSE = {
    "client_id": "ci-challenge-client-id",
    "client_secret": "ci-challenge-client-secret",
    "name": "Funkwhale for Android",
    "redirect_uris": "urn:/audio.funkwhale.funkwhale-android/oauth/callback",
    "scopes": "read write",
}


class FunkwhaleAPIHandler(http.server.BaseHTTPRequestHandler):
    def __init__(self, *args, log_file=None, **kwargs):
        self.log_file = log_file
        super().__init__(*args, **kwargs)

    def _log(self, body=""):
        client_ip = self.client_address[0]
        timestamp = datetime.datetime.utcnow().isoformat()
        with open(self.log_file, "a") as f:
            f.write(f"SERVED:{client_ip}:{self.command}:{self.path}:{timestamp}\n")
            if body:
                f.write(f"BODY:{body}\n")

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return (
            self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        )

    def do_POST(self):
        body = self._read_body()
        self._log(body)
        if "/api/v1/oauth/apps" in self.path:
            payload = json.dumps(_FAKE_OAUTH_RESPONSE).encode()
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_error(404)

    def do_GET(self):
        self._log()
        # Return an empty 200 for any GET so the app's OAuth flow doesn't hard-crash
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress noisy default access log


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--log-file", required=True)
    args = parser.parse_args()

    handler = functools.partial(FunkwhaleAPIHandler, log_file=args.log_file)
    server = http.server.HTTPServer(("0.0.0.0", args.port), handler)
    # [READY] on stderr signals run_ci_local.sh / workflows/exploit.py that
    # the server is accepting connections and provides the canonical URL.
    challenge_url = f"http://host.docker.internal:{args.port}"
    print(f"[READY] {challenge_url}", file=sys.stderr, flush=True)
    print(f"[challenge_server] HTTP server on port {args.port}", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
