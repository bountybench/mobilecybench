#!/usr/bin/env python3
"""
mobilecybench host agent: start/stop emulator and proxy adb commands.

Token file: <repo>/ssh_key
"""

import os
import sys
import json
import subprocess
import shlex
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from shutil import which

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("MCB_AGENT_PORT", "52888"))
TOKEN_FILE = os.path.join(REPO_ROOT, "ssh_key")
LOGFILE = os.path.expanduser("~/mobilecybench-agent.log")

def log(s):
    try:
        with open(LOGFILE, "a") as f:
            f.write(f"{s}\n")
    except Exception:
        pass
    print(s)

def read_token():
    try:
        with open(TOKEN_FILE, "r") as f:
            return f.read().strip()
    except Exception as e:
        log(f"read_token: cannot open token file {TOKEN_FILE}: {e}")
        return None

def extract_token_from_request(handler, query, body_token=None):
    # Accept X-MCB-TOKEN, Authorization: Bearer <token>, query token, or JSON body token
    token = None

    # case-insensitive
    def header_get(h):
        for k in handler.headers:
            if k.lower() == h.lower():
                return handler.headers[k]
        return None

    # Try X-MCB-TOKEN header
    hdr = header_get("X-MCB-TOKEN")
    if hdr:
        token = hdr.strip()
    else:
        # Try Authorization: Bearer <token>
        auth = header_get("Authorization") or header_get("authorization")
        if auth:
            parts = auth.split(None, 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                token = parts[1].strip()

    # query param
    if not token and "token" in query:
        token = query["token"][0].strip()

    # body token
    if not token and body_token:
        token = str(body_token).strip()

    expected = read_token()
    if not expected:
        log("Authorization denied: no expected token configured on host.")
        return False

    if token == expected:
        return True
    else:
        log(f"Authorization failed: supplied token mismatch from {handler.client_address}")
        return False

def find_adb_executable():
    p = which("adb")
    if p:
        return p
    candidates = [
        os.path.expanduser(os.path.join("~", ".android-sdk", "platform-tools", "adb")),
        os.path.join(REPO_ROOT, ".android-sdk", "platform-tools", "adb"),
        "/usr/local/bin/adb",
        "/usr/bin/adb",
        "/opt/homebrew/bin/adb",
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None

def run_bg(script_path):
    try:
        p = subprocess.Popen(["/bin/bash", script_path], cwd=REPO_ROOT,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, f"started pid={p.pid}"
    except Exception as e:
        return False, str(e)

def run_cmd_capture(cmd, timeout=300):
    try:
        res = subprocess.run(cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        return {
            "stdout": res.stdout.decode(errors="replace"),
            "stderr": res.stderr.decode(errors="replace"),
            "exit_code": res.returncode
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"timeout after {timeout}s", "exit_code": 124}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "exit_code": 1}

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send_json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/status":
            self._send_json(200, {"ok": True, "repo": REPO_ROOT})
            return
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"not found\n")

    def do_POST(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        length = int(self.headers.get("Content-Length") or 0)
        body_bytes = self.rfile.read(length) if length > 0 else b""
        body_json = None
        body_token = None
        if body_bytes:
            try:
                body_json = json.loads(body_bytes.decode())
                if isinstance(body_json, dict):
                    body_token = body_json.get("token")
            except Exception:
                body_json = None

        if parsed.path == "/push_file":
            # Accepts JSON: {"filename": "<name>", "data_b64": "<base64-encoded bytes>"}
            if not extract_token_from_request(self, query, body_token):
                self._send_json(403, {"error": "forbidden"})
                log(f"Unauthorized push_file attempt from {self.client_address!r}")
                return
            if not body_json or "filename" not in body_json or "data_b64" not in body_json:
                self._send_json(400, {"error": "missing filename or data_b64 in JSON body"})
                return
            try:
                import base64, uuid
                fname = os.path.basename(str(body_json["filename"]))
                data_b64 = str(body_json["data_b64"])
                data = base64.b64decode(data_b64.encode())
                dest_dir = os.path.join(REPO_ROOT, "tmp")
                os.makedirs(dest_dir, exist_ok=True)
                dest_path = os.path.join(dest_dir, f"{uuid.uuid4().hex}_{fname}")
                with open(dest_path, "wb") as fh:
                    fh.write(data)
                log(f"/push_file saved {fname} -> {dest_path} from {self.client_address!r}")
                self._send_json(200, {"path": dest_path})
            except Exception as e:
                log(f"/push_file error: {e}")
                self._send_json(500, {"error": "failed to save file", "detail": str(e)})
            return
        # /start
        if parsed.path == "/start":
            if not extract_token_from_request(self, query, body_token):
                self._send_json(403, {"error": "forbidden"})
                log(f"Unauthorized attempt from {self.client_address}")
                return
            script = os.path.join(REPO_ROOT, "start_emulator.sh")
            if not os.path.isfile(script) or not os.access(script, os.X_OK):
                self._send_json(500, {"error": "start script missing or not executable"})
                log("start_emulator.sh missing/not executable")
                return
            ok, msg = run_bg(script)
            self._send_json(200 if ok else 500, {"result": msg})
            log(f"/start -> {msg} by {self.client_address}")
            return

        # /stop
        if parsed.path == "/stop":
            if not extract_token_from_request(self, query, body_token):
                self._send_json(403, {"error": "forbidden"})
                log(f"Unauthorized attempt from {self.client_address}")
                return
            script = os.path.join(REPO_ROOT, "stop_emulator.sh")
            if not os.path.isfile(script) or not os.access(script, os.X_OK):
                res = run_cmd_capture(["adb", "emu", "kill"], timeout=10)
                self._send_json(200, res)
                log("/stop attempted fallback adb emu kill")
                return
            res = run_cmd_capture([script], timeout=30)
            self._send_json(200, res)
            log("/stop -> done")
            return

        # /status via POST (authenticated variant)
        if parsed.path == "/status":
            if not extract_token_from_request(self, query, body_token):
                self._send_json(403, {"error": "forbidden"})
                log(f"Unauthorized attempt from {self.client_address}")
                return
            self._send_json(200, {"ok": True, "repo": REPO_ROOT})
            return

        # /adb - proxy
        if parsed.path == "/adb":
            if not extract_token_from_request(self, query, body_token):
                self._send_json(403, {"error": "forbidden"})
                log(f"Unauthorized attempt from {self.client_address}")
                return
            if not body_json or "args" not in body_json:
                self._send_json(400, {"error": "missing args array in JSON body"})
                return
            args = body_json.get("args") or []
            if not isinstance(args, list):
                self._send_json(400, {"error": "args must be an array"})
                return
            adb_path = find_adb_executable()
            if not adb_path:
                self._send_json(500, {"error": "adb not found on host; ensure platform-tools installed"})
                log("adb not found on host")
                return
            cmd = [adb_path] + [str(a) for a in args]
            res = run_cmd_capture(cmd, timeout=300)
            self._send_json(200, res)
            log(f"/adb -> ran: {shlex.join(cmd)} by {self.client_address}")
            return

        self._send_json(404, {"error": "not found"})
        return

def run():

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    log(f"mobilecybench host-agent listening on 0.0.0.0:{PORT}, repo={REPO_ROOT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    run()

