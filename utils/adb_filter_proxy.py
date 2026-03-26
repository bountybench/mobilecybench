#!/usr/bin/env python3
"""Filtering ADB proxy that blocks root/su commands.

Sits between the ADB client in the kali container and the real ADB server
on the host, inspecting protocol messages and rejecting dangerous ones.

Usage:
    python3 adb_filter_proxy.py [listen_port] [upstream_host] [upstream_port]

Defaults: listen on :5037, forward to adb-server:5037

Upstream host can also be set via ADB_UPSTREAM_HOST env var.
"""

import os
import re
import socket
import sys
import threading

try:
    from adb_blocked_patterns import ALL_SHELL_PATTERNS, BLOCKED_SERVICES
except ImportError:
    # Fallback when running standalone (e.g. inside the sidecar container
    # before adb_blocked_patterns.py is copied alongside this script).
    from utils.adb_blocked_patterns import ALL_SHELL_PATTERNS, BLOCKED_SERVICES


def _parse_args():
    """Parse CLI args, falling back to env vars / defaults."""
    try:
        listen = int(sys.argv[1]) if len(sys.argv) > 1 else 5037
    except ValueError:
        listen = 5037
    upstream_host = (
        sys.argv[2]
        if len(sys.argv) > 2
        else os.environ.get("ADB_UPSTREAM_HOST", "adb-server")
    )
    try:
        upstream_port = int(sys.argv[3]) if len(sys.argv) > 3 else 5037
    except ValueError:
        upstream_port = 5037
    return listen, upstream_host, upstream_port


LISTEN_PORT, UPSTREAM_HOST, UPSTREAM_PORT = _parse_args()

# Encode for byte-level matching in the proxy.
_BLOCKED_SERVICES_B = [s.encode() for s in BLOCKED_SERVICES]
_BLOCKED_SHELL_PATTERNS_B = [p.encode() for p in ALL_SHELL_PATTERNS]


def is_blocked(data: bytes) -> tuple:
    """Check if an ADB protocol message should be blocked.

    Returns (blocked: bool, reason: str).
    """
    if len(data) <= 4:
        return False, ""
    payload = data[4:]

    for svc in _BLOCKED_SERVICES_B:
        if payload.startswith(svc):
            return True, "blocked service: " + svc.decode()

    # Check shell: and exec: services — both can run arbitrary commands.
    # exec: (used by "adb exec-out") is functionally identical to shell:.
    _CMD_PREFIXES = (b"shell:", b"shell,", b"exec:", b"exec,")
    for prefix in _CMD_PREFIXES:
        if payload.startswith(prefix):
            cmd = payload.split(b":", 1)[1] if b":" in payload else payload
            for pattern in _BLOCKED_SHELL_PATTERNS_B:
                if re.search(pattern, cmd):
                    return True, "blocked command: " + cmd[:100].decode(
                        errors="replace"
                    )
            break

    return False, ""


def proxy_data(src, dst, direction: str, should_filter: bool = False):
    """Forward data between sockets, optionally filtering."""
    try:
        while True:
            data = src.recv(8192)
            if not data:
                break
            if should_filter:
                blocked, reason = is_blocked(data)
                if blocked:
                    print(f"[BLOCKED] {direction}: {reason}", flush=True)
                    fail_msg = "blocked by security proxy"
                    fail_resp = f"FAIL{len(fail_msg):04x}{fail_msg}".encode()
                    src.sendall(fail_resp)
                    break
            dst.sendall(data)
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            src.shutdown(socket.SHUT_RD)
        except OSError:
            pass
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle_client(client_sock, addr):
    """Handle one ADB client connection."""
    try:
        upstream = socket.create_connection((UPSTREAM_HOST, UPSTREAM_PORT), timeout=5)
    except Exception as e:
        print(f"[ERROR] Cannot connect upstream: {e}", flush=True)
        client_sock.close()
        return

    t1 = threading.Thread(
        target=proxy_data,
        args=(client_sock, upstream, "client->server", True),
        daemon=True,
    )
    t2 = threading.Thread(
        target=proxy_data,
        args=(upstream, client_sock, "server->client", False),
        daemon=True,
    )
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    client_sock.close()
    upstream.close()


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", LISTEN_PORT))
    server.listen(32)
    print(
        f"[PROXY] ADB filter proxy on :{LISTEN_PORT} -> "
        f"{UPSTREAM_HOST}:{UPSTREAM_PORT}",
        flush=True,
    )

    while True:
        client, addr = server.accept()
        threading.Thread(target=handle_client, args=(client, addr), daemon=True).start()


if __name__ == "__main__":
    main()
