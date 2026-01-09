#!/usr/bin/env python3
"""Minimal HTTP listener to record SSRF-style requests."""

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import json
import time

LOG_FILE = Path(__file__).resolve().parent / "ssrf_requests.json"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        entry = {
            "time": int(time.time()),
            "path": self.path,
            "client": self.client_address[0],
        }
        try:
            data = []
            if LOG_FILE.exists():
                data = json.loads(LOG_FILE.read_text())
            data.append(entry)
            LOG_FILE.write_text(json.dumps(data, indent=2))
        except Exception:
            pass
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, fmt: str, *args: object) -> None:
        return


def main() -> None:
    server = HTTPServer(("0.0.0.0", 8001), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
