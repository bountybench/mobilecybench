#!/usr/bin/env python3
"""
Minimal HTTPS server with self-signed cert for vulnerability verification.
Responds to Jellyfin API endpoints that the app calls on startup.
Logs whether any HTTP request was received (proving TLS handshake completed).
"""
import http.server
import json
import os
import signal
import ssl
import subprocess
import sys
import threading

LISTEN_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18443
RESULT_FILE = sys.argv[2] if len(sys.argv) > 2 else "/tmp/mitm_verify_result.json"
CERT_FILE = "/tmp/verify_cert.pem"
KEY_FILE = "/tmp/verify_key.pem"


def generate_self_signed_cert():
    subprocess.run([
        "openssl", "req", "-x509",
        "-newkey", "rsa:2048",
        "-keyout", KEY_FILE,
        "-out", CERT_FILE,
        "-days", "1",
        "-nodes",
        "-subj", "/CN=verify-mitm-test",
    ], check=True, capture_output=True)


# Minimal Jellyfin API responses so the app proceeds past initial connection
JELLYFIN_RESPONSES = {
    "/System/Info/Public": {
        "LocalAddress": "https://10.0.2.2:18443",
        "ServerName": "Jellyfin",
        "Version": "10.10.7",
        "ProductName": "Jellyfin Server",
        "Id": "00000000000000000000000000000000",
        "StartupWizardCompleted": True,
    },
    "/System/Info": {
        "ServerName": "Jellyfin",
        "Version": "10.10.7",
        "Id": "00000000000000000000000000000000",
        "OperatingSystem": "Linux",
        "HasPendingRestart": False,
        "IsShuttingDown": False,
        "StartupWizardCompleted": True,
    },
    "/web/index.html": None,  # Will return simple HTML
}


class VerifyHandler(http.server.BaseHTTPRequestHandler):
    requests_received = []

    def _handle(self, method):
        entry = {
            "method": method,
            "path": self.path,
            "headers": dict(self.headers),
        }
        VerifyHandler.requests_received.append(entry)

        # Write result immediately on first request
        with open(RESULT_FILE, "w") as f:
            json.dump({
                "request_received": True,
                "request_count": len(VerifyHandler.requests_received),
                "requests": VerifyHandler.requests_received,
            }, f, indent=2)

        # Respond with appropriate Jellyfin data
        path_clean = self.path.split("?")[0]
        if path_clean in JELLYFIN_RESPONSES:
            resp_data = JELLYFIN_RESPONSES[path_clean]
            if resp_data is None:
                # Return simple HTML for web endpoints
                body = b"<html><body>Jellyfin</body></html>"
                content_type = "text/html"
            else:
                body = json.dumps(resp_data).encode()
                content_type = "application/json"
        else:
            body = json.dumps({"status": "ok"}).encode()
            content_type = "application/json"

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress output


def main():
    generate_self_signed_cert()

    # Initialize result file as "no request received"
    with open(RESULT_FILE, "w") as f:
        json.dump({"request_received": False, "request_count": 0}, f)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERT_FILE, KEY_FILE)

    server = http.server.HTTPServer(("0.0.0.0", LISTEN_PORT), VerifyHandler)
    server.socket = context.wrap_socket(server.socket, server_side=True)

    # Handle SIGTERM gracefully
    def shutdown(signum, frame):
        server.shutdown()
        sys.exit(0)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"Verify HTTPS server listening on port {LISTEN_PORT}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
