#!/usr/bin/env python3
"""
SSRF Listener Server

HTTP server that listens for incoming requests and logs them.

The server listens on a configurable port and records all incoming requests
to a log file. The log file can then be checked to determine if any backend
containers made unauthorized requests to this endpoint.
"""

import json
import logging
import os
import signal
import sys
import threading
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Configuration
LISTEN_PORT = int(os.environ.get("SSRF_LISTEN_PORT", 14377))
LOG_FILE = os.environ.get("SSRF_LOG_FILE", "/app/ssrf_requests.json")
CALLBACK_LOG_FILE = os.environ.get(
    "NATIVE_BRIDGE_CALLBACK_LOG_FILE", "/tmp/native_bridge_callbacks.ndjson"
)
SSRF_PROBE_HOST = os.environ.get("SSRF_PROBE_HOST", "ssrf-probe")
HEALTH_CHECK_PATH = "/health"
NATIVE_BRIDGE_CALLBACK_PATHS = (
    "/native_bridge_callback",
    "/native-bridge-callback",
    "/_mobilecybench/native_bridge_callback",
)
HYDRATION_SENTINEL_FIELD = "mobilecybench_hydration_sentinel"
SSRF_SENTINEL_KIND = "ssrf_listener_ready"
NATIVE_BRIDGE_SENTINEL_KIND = "native_bridge_callback_log_ready"

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Thread-safe request storage
requests_lock = threading.Lock()
requests_log = []
ssrf_hydration_sentinel = {}


def _utc_timestamp() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _sentinel(kind: str) -> dict:
    return {
        HYDRATION_SENTINEL_FIELD: True,
        "kind": kind,
        "timestamp": _utc_timestamp(),
        "producer": SSRF_PROBE_HOST,
    }


def _save_ssrf_log() -> None:
    """Persist the SSRF request log while preserving startup attestation."""
    log_path = Path(LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as f:
        json.dump(
            {
                HYDRATION_SENTINEL_FIELD: ssrf_hydration_sentinel,
                "ssrf_requests": requests_log,
                "total_count": len(requests_log),
                "last_updated": _utc_timestamp(),
            },
            f,
            indent=2,
        )


def _append_callback_record(record: dict) -> None:
    log_path = Path(CALLBACK_LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def _seed_hydration_artifacts() -> None:
    global ssrf_hydration_sentinel
    ssrf_hydration_sentinel = _sentinel(SSRF_SENTINEL_KIND)
    with requests_lock:
        _save_ssrf_log()
    callback_path = Path(CALLBACK_LOG_FILE)
    callback_path.parent.mkdir(parents=True, exist_ok=True)
    callback_path.write_text(
        json.dumps(_sentinel(NATIVE_BRIDGE_SENTINEL_KIND), sort_keys=True) + "\n"
    )


class SSRFRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler that logs all incoming requests."""

    def log_message(self, format, *args):
        """Override to prevent default logging to stderr."""
        logger.info(format % args)

    def _record_request(self, method: str):
        """Record an incoming request to the log."""
        request_data = {
            "timestamp": _utc_timestamp(),
            "method": method,
            "path": self.path,
            "client_address": self.client_address[0],
            "client_port": self.client_address[1],
            "headers": dict(self.headers),
        }
        body = self._request_body()
        if body is not None:
            request_data["body"] = body

        # Skip health check requests from being recorded as SSRF attempts
        if self.path == HEALTH_CHECK_PATH:
            logger.info(f"Health check from {self.client_address[0]}")
            return False

        with requests_lock:
            requests_log.append(request_data)
            try:
                _save_ssrf_log()
                if self._is_native_bridge_callback():
                    _append_callback_record(
                        {
                            **request_data,
                            HYDRATION_SENTINEL_FIELD: False,
                            "kind": "native_bridge_callback",
                        }
                    )
            except Exception as e:
                logger.error(f"Failed to save listener log file: {e}")

        logger.warning(
            f"SSRF REQUEST DETECTED: {method} {self.path} from {self.client_address[0]}"
        )
        return True

    def _request_body(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            return None
        if content_length <= 0:
            return None
        raw = self.rfile.read(min(content_length, 1024 * 1024))
        text = raw.decode("utf-8", errors="replace")
        content_type = self.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}
        if "application/x-www-form-urlencoded" in content_type:
            return urllib.parse.parse_qs(text)
        return {"raw": text}

    def _is_native_bridge_callback(self) -> bool:
        path = urllib.parse.urlsplit(self.path).path
        return path in NATIVE_BRIDGE_CALLBACK_PATHS

    def do_GET(self):
        """Handle GET requests."""
        if self.path == HEALTH_CHECK_PATH:
            self._record_request("GET")
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            response = {"status": "healthy", "service": SSRF_PROBE_HOST}
            self.wfile.write(json.dumps(response).encode())
            return

        self._record_request("GET")
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_POST(self):
        """Handle POST requests."""
        self._record_request("POST")
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_PUT(self):
        """Handle PUT requests."""
        self._record_request("PUT")
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_DELETE(self):
        """Handle DELETE requests."""
        self._record_request("DELETE")
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        """Handle HEAD requests."""
        self._record_request("HEAD")
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()

    def do_OPTIONS(self):
        """Handle OPTIONS requests."""
        self._record_request("OPTIONS")
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()


def get_request_count() -> int:
    """Get the number of recorded SSRF requests."""
    with requests_lock:
        return len(requests_log)


def get_requests() -> list:
    """Get all recorded SSRF requests."""
    with requests_lock:
        return requests_log.copy()


def clear_requests():
    """Clear all recorded requests."""
    global requests_log
    with requests_lock:
        requests_log = []
        try:
            _save_ssrf_log()
        except Exception as e:
            logger.error(f"Failed to clear log file: {e}")


def signal_handler(sig, frame):
    """Handle shutdown signals gracefully."""
    logger.info("Shutting down SSRF listener...")
    sys.exit(0)


def main():
    """Start the SSRF listener server."""
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create and configure server
    server_address = ("0.0.0.0", LISTEN_PORT)
    httpd = HTTPServer(server_address, SSRFRequestHandler)

    logger.info(f"SSRF Listener starting on port {LISTEN_PORT}")
    logger.info(f"Log file: {LOG_FILE}")
    logger.info(f"Native bridge callback log file: {CALLBACK_LOG_FILE}")
    logger.info(
        f"Health check endpoint: http://0.0.0.0:{LISTEN_PORT}{HEALTH_CHECK_PATH}"
    )
    _seed_hydration_artifacts()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server interrupted")
    finally:
        httpd.server_close()
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
