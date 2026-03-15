#!/usr/bin/env python3
"""Challenge server for Funkwhale cleartext transmission vulnerability.

Logs each request with client IP and body so verify_exploit.sh can confirm
the OAuth registration came from the emulator (127.0.0.1), not the exploit
container.
"""

import argparse
import datetime
import functools
import http.server
import json
import sys

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
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--log-file", required=True)
    args = parser.parse_args()

    handler = functools.partial(FunkwhaleAPIHandler, log_file=args.log_file)
    server = http.server.HTTPServer(("0.0.0.0", args.port), handler)
    challenge_url = f"http://host.docker.internal:{args.port}"
    print(f"[READY] {challenge_url}", file=sys.stderr, flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
