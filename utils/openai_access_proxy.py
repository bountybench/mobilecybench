"""OpenAI Responses proxy sidecar: adds an access program, holds the key, enforces a spend cap.

opencode's OpenAI provider drops unknown request fields, so it cannot send
``access_programs``. The agent instead points opencode at this proxy
(``baseURL=http://openai-proxy:8080/v1``) with a dummy key. The proxy

- adds ``access_programs`` to every ``/responses`` request body,
- replaces the Authorization header with the real key (the agent never sees it),
- streams the response back unchanged,
- appends each request's token usage and estimated cost to a ledger, and
- refuses new requests (HTTP 429) once the ledger total reaches the cap.

Configuration (environment):
    OPENAI_PROXY_KEY_FILE    file holding the real API key (first line)
    OPENAI_PROXY_LEDGER      JSONL ledger path (shared across runs on one host)
    OPENAI_PROXY_CAP_USD     spend cap for this ledger
    OPENAI_PROXY_ACCESS      JSON object for access_programs, e.g. {"cyber": "daybreak_blue"}
    OPENAI_PROXY_PRICES      JSON {"input": usd/Mtok, "cached": usd/Mtok, "output": usd/Mtok}
    OPENAI_PROXY_RUN         label written to each ledger row
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "api.openai.com"
PORT = 8080
HOP_HEADERS = {"host", "authorization", "content-length", "connection", "accept-encoding",
               "transfer-encoding", "keep-alive", "proxy-connection", "te", "upgrade"}

KEY = open(os.environ["OPENAI_PROXY_KEY_FILE"]).readline().strip()
LEDGER = os.environ["OPENAI_PROXY_LEDGER"]
CAP = float(os.environ["OPENAI_PROXY_CAP_USD"])
ACCESS = json.loads(os.environ.get("OPENAI_PROXY_ACCESS") or "{}")
PRICES = json.loads(os.environ["OPENAI_PROXY_PRICES"])
RUN = os.environ.get("OPENAI_PROXY_RUN", "")
_lock = threading.Lock()


def spent() -> float:
    try:
        with open(LEDGER) as f:
            return sum(json.loads(l).get("usd", 0.0) for l in f if l.strip())
    except FileNotFoundError:
        return 0.0


def record(usage: dict, model: str, effort) -> None:
    inp = usage.get("input_tokens", 0) or 0
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    usd = ((inp - cached) * PRICES["input"] + cached * PRICES["cached"] + out * PRICES["output"]) / 1e6
    row = {"t": time.time(), "run": RUN, "model": model, "effort": effort,
           "input": inp, "cached": cached, "output": out, "usd": round(usd, 6)}
    with _lock, open(LEDGER, "a") as f:
        f.write(json.dumps(row) + "\n")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _error(self, code: int, message: str) -> None:
        body = json.dumps({"error": {"message": message, "type": "proxy_error"}}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._forward(None)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        self._forward(self.rfile.read(n))

    def _forward(self, body: bytes | None) -> None:
        if spent() >= CAP:
            self._error(429, f"spend cap of ${CAP:.2f} reached for this host")
            return
        model, effort = "", None
        if body and self.path.rstrip("/").endswith("/responses"):
            req = json.loads(body)
            if ACCESS:
                req["access_programs"] = ACCESS
            model, effort = req.get("model", ""), (req.get("reasoning") or {}).get("effort")
            body = json.dumps(req).encode()
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}
        headers["Authorization"] = f"Bearer {KEY}"
        if body is not None:
            headers["Content-Length"] = str(len(body))
        conn = http.client.HTTPSConnection(UPSTREAM, timeout=900)
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
        except Exception as e:  # upstream unreachable
            self._error(502, f"upstream error: {e}")
            return
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() not in HOP_HEADERS and k.lower() != "content-encoding":
                self.send_header(k, v)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        streaming = "event-stream" in (resp.getheader("Content-Type") or "")
        buf, full, usage = b"", b"", None
        while True:
            chunk = resp.read1(65536)
            if not chunk:
                break
            self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
            self.wfile.flush()
            if not streaming:
                full += chunk
                continue
            buf += chunk
            # SSE: usage arrives in the response.completed event.
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.startswith(b"data: ") and b'"response.completed"' in line:
                    try:
                        usage = json.loads(line[6:])["response"].get("usage")
                    except Exception:
                        pass
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()
        if not streaming and full.strip().startswith(b"{"):
            try:
                usage = json.loads(full).get("usage")
            except Exception:
                pass
        if usage:
            record(usage, model, effort)
        elif model:
            record({}, model, effort)  # count the request even if no usage was returned
        conn.close()


if __name__ == "__main__":
    print(f"openai proxy on :{PORT}, cap ${CAP:.2f}, spent ${spent():.2f}", flush=True)
    sys.stdout.flush()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
