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
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Configuration
LISTEN_PORT = int(os.environ.get("SSRF_LISTEN_PORT", 8080))
LOG_FILE = os.environ.get("SSRF_LOG_FILE", "/app/ssrf_requests.json")
HEALTH_CHECK_PATH = "/health"

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Thread-safe request storage
requests_lock = threading.Lock()
requests_log = []


class SSRFRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler that logs all incoming requests."""

    def log_message(self, format, *args):
        """Override to prevent default logging to stderr."""
        logger.info(format % args)

    def _record_request(self, method: str):
        """Record an incoming request to the log."""
        request_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "method": method,
            "path": self.path,
            "client_address": self.client_address[0],
            "client_port": self.client_address[1],
            "headers": dict(self.headers),
        }

        # Skip health check requests from being recorded as SSRF attempts
        if self.path == HEALTH_CHECK_PATH:
            logger.info(f"Health check from {self.client_address[0]}")
            return False

        with requests_lock:
            requests_log.append(request_data)
            # Persist to file
            self._save_log()

        logger.warning(
            f"SSRF REQUEST DETECTED: {method} {self.path} from {self.client_address[0]}"
        )
        return True

    def _save_log(self):
        """Save the request log to file."""
        try:
            log_path = Path(LOG_FILE)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "w") as f:
                json.dump(
                    {
                        "ssrf_requests": requests_log,
                        "total_count": len(requests_log),
                        "last_updated": datetime.utcnow().isoformat() + "Z",
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"Failed to save log file: {e}")

    def do_GET(self):
        """Handle GET requests."""
        if self.path == HEALTH_CHECK_PATH:
            self._record_request("GET")
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            response = {"status": "healthy", "service": "ssrf-probe"}
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
        # Clear the log file
        try:
            log_path = Path(LOG_FILE)
            if log_path.exists():
                log_path.unlink()
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
    logger.info(
        f"Health check endpoint: http://0.0.0.0:{LISTEN_PORT}{HEALTH_CHECK_PATH}"
    )

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server interrupted")
    finally:
        httpd.server_close()
        logger.info("Server stopped")


if __name__ == "__main__":
    main()
