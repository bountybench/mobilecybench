#!/usr/bin/env python3
import base64
import json
import os
import ssl
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROLE = os.environ.get("HYDRATION_ROLE", "receiver")
RUN_ID = os.environ.get("HYDRATION_RUN_ID", "hydration_unknown")
MEDIA_PORT = os.environ.get("HYDRATION_MEDIA_PORT", "18080")
LOG_DIR = Path("/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def redact_headers(headers):
    out = {}
    for key, value in headers.items():
        if key.lower() in {"authorization", "cookie", "x-openhab-token"}:
            out[key] = "<redacted-present>" if value else ""
        else:
            out[key] = value
    return out


def auth_facts(headers):
    value = headers.get("Authorization")
    facts = {
        "authorization_present": bool(value),
        "authorization_scheme": None,
        "authorization_value_redacted": bool(value),
        "basic_decodable": False,
        "openhab_auth": "not_checked",
    }
    if not value:
        return facts
    parts = value.split(None, 1)
    if parts:
        facts["authorization_scheme"] = parts[0].lower()
    if len(parts) == 2 and parts[0].lower() == "basic":
        try:
            base64.b64decode(parts[1], validate=True)
            facts["basic_decodable"] = True
        except Exception:
            facts["basic_decodable"] = False
    return facts


def redact_query(parsed_query):
    out = {}
    for key, value in parsed_query.items():
        values = value if isinstance(value, list) else [value]
        if key.lower() in {"regid", "token", "authorization", "password"}:
            out[key] = ["<redacted-present>" for item in values if item]
        else:
            out[key] = values
    return out


def query_facts(parsed_query):
    facts = {}
    for key, value in parsed_query.items():
        values = value if isinstance(value, list) else [value]
        facts[key] = {
            "present": any(bool(item) for item in values),
            "count": len(values),
        }
    return facts


def write_log(entry):
    entry["timestamp"] = now_iso()
    entry["role"] = ROLE
    entry["run_id"] = RUN_ID
    with (LOG_DIR / "requests.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


class Receiver(BaseHTTPRequestHandler):
    server_version = "OpenHABHydrationReceiver/1.0"

    def log_message(self, _fmt, *_args):
        return

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(length) if length else b""

    def record(self, body=b""):
        parsed = urlparse(self.path)
        write_log(
            {
                "method": self.command,
                "path": parsed.path,
                "query": redact_query(parse_qs(parsed.query)),
                "query_facts": query_facts(parse_qs(parsed.query)),
                "headers": redact_headers(self.headers),
                "auth": auth_facts(self.headers),
                "body_len": len(body),
                "body_preview": "<redacted-present>" if body else "",
            }
        )

    def send_json(self, payload, status=200):
        data = json.dumps(payload, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_html(self, html, status=200):
        data = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.record()
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/health":
            self.send_json({"ok": True, "role": ROLE, "run_id": RUN_ID})
            return
        if ROLE == "media" and path == f"/media/hydration/{RUN_ID}/image.png":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(PNG_BYTES)))
            self.end_headers()
            self.wfile.write(PNG_BYTES)
            return
        if ROLE == "cloud":
            self.handle_cloud_get(path)
            return
        if ROLE == "webview":
            self.handle_webview_get(path)
            return
        self.send_json({"ok": True, "role": ROLE, "run_id": RUN_ID, "path": path})

    def do_POST(self):
        body = self.read_body()
        self.record(body)
        self.send_json({"ok": True, "role": ROLE, "run_id": RUN_ID, "captured": True})

    def do_PUT(self):
        self.do_POST()

    def handle_cloud_get(self, path):
        if (
            path.endswith("/settings/notifications")
            or path == "/api/v1/settings/notifications"
        ):
            self.send_json(
                {
                    "enabled": True,
                    "polling": True,
                    "run_id": RUN_ID,
                    "message": f"cloud-notification-{RUN_ID}",
                }
            )
            return
        if path.endswith("/notifications") or path == "/api/v1/notifications":
            self.send_json(
                [
                    {
                        "id": f"hydration-{RUN_ID}",
                        "message": f"cloud-notification-{RUN_ID}",
                        "created": now_iso(),
                        "icon": f"http://hydration-attacker.test:{MEDIA_PORT}/media/hydration/{RUN_ID}/image.png",
                        "actions": [
                            {
                                "label": "Hydration action",
                                "item": f"Hydration_Notification_Action_{RUN_ID}",
                                "command": f"notification-action-command-{RUN_ID}",
                            }
                        ],
                    }
                ]
            )
            return
        self.send_json({"ok": True, "cloud": True, "run_id": RUN_ID, "path": path})

    def handle_webview_get(self, path):
        if (
            path.startswith(("/webview", "/habpanel", "/frontail", "/permission"))
            or path == "/"
        ):
            page = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>openHAB hydration {RUN_ID}</title></head>
<body>
<h1>webview-js-bridge-{RUN_ID}</h1>
<a id="same-host" href="/webview/hydration/{RUN_ID}/same-host">same-host</a>
<a id="cross-host" href="http://hydration-attacker.test:{MEDIA_PORT}/cross-host-redirect-{RUN_ID}">cross-host</a>
<script>
window.hydrationRunId = "{RUN_ID}";
function callBridge(name, args) {{
  try {{
    if (window.OHApp && typeof window.OHApp[name] === "function") {{
      return window.OHApp[name].apply(window.OHApp, args || []);
    }}
  }} catch (e) {{
    fetch("/bridge-error/{RUN_ID}?method=" + encodeURIComponent(name) + "&message=" + encodeURIComponent(String(e)));
  }}
}}
callBridge("setScreenOn", [true]);
callBridge("getVersion", []);
callBridge("nonExposedHydrationMethod", ["webview-js-bridge-{RUN_ID}"]);
if (location.pathname.indexOf("/permission") === 0 && navigator.mediaDevices) {{
  navigator.mediaDevices.getUserMedia({{audio: true, video: true}}).catch(function(err) {{
    fetch("/permission-result/{RUN_ID}?error=" + encodeURIComponent(String(err)));
  }});
}}
</script>
</body>
</html>
"""
            self.send_html(page)
            return
        self.send_json({"ok": True, "webview": True, "run_id": RUN_ID, "path": path})


def serve(port, use_tls=False):
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Receiver)
    if use_tls:
        cert = Path("/certs/hydration-selfsigned.crt")
        key = Path("/certs/hydration-selfsigned.key")
        if not cert.exists() or not key.exists():
            return
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
    httpd.serve_forever()


if ROLE == "webview":
    threading.Thread(target=serve, args=(8443, True), daemon=True).start()
serve(8080, False)
