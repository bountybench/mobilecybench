#!/usr/bin/env python3
"""Capture cleartext HTTP request metadata into a harness-owned JSON artifact."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

OUTPUT_PATH = Path(
    os.environ.get("PACKET_CAPTURE_OUTPUT", "/captures/packet_capture.json")
)
INTERFACE = os.environ.get("PACKET_CAPTURE_INTERFACE", "any")
CAPTURE_FILTER = os.environ.get(
    "PACKET_CAPTURE_FILTER", "tcp port 14378 or tcp port 80"
)
SENTINEL_URL = os.environ.get(
    "PACKET_CAPTURE_SENTINEL_URL",
    "http://127.0.0.1:14378/_mobilecybench/packet_capture_sentinel",
)

HYDRATION_SENTINEL_FIELD = "mobilecybench_hydration_sentinel"
PACKET_SENTINEL_FIELD = "mobilecybench_packet_capture_sentinel"
PACKET_SENTINEL_KIND = "packet_capture_ready"
REQUEST_LINE_RE = re.compile(
    r"^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+(\S+)\s+HTTP/"
)

records_lock = threading.Lock()
records: list[dict[str, Any]] = []
packet_sentinel: dict[str, Any] | None = None
current_record: dict[str, Any] | None = None
tcpdump_process: subprocess.Popen[str] | None = None


def _utc_timestamp() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _hydration_sentinel() -> dict[str, Any]:
    return {
        "kind": PACKET_SENTINEL_KIND,
        "timestamp": _utc_timestamp(),
        "producer": "home-assistant-packet-capture",
    }


def _write_artifact() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        HYDRATION_SENTINEL_FIELD: _hydration_sentinel(),
        PACKET_SENTINEL_FIELD: packet_sentinel,
        "http_requests": records,
        "total_count": len(records),
        "last_updated": _utc_timestamp(),
    }
    temp_path = OUTPUT_PATH.with_suffix(OUTPUT_PATH.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temp_path.replace(OUTPUT_PATH)


def _append_record(record: dict[str, Any]) -> None:
    with records_lock:
        records.append(record)
        _write_artifact()


def _update_current_host(host: str) -> None:
    global current_record
    if current_record is None:
        return
    current_record["host"] = host
    current_record["url"] = f"http://{host}{current_record.get('path', '/')}"
    with records_lock:
        _write_artifact()


def _send_sentinel_request() -> None:
    global packet_sentinel
    time.sleep(1.0)
    try:
        urllib.request.urlopen(SENTINEL_URL, timeout=5).read()
        packet_sentinel = {
            "kind": PACKET_SENTINEL_KIND,
            "capture_phase": "hydration",
            "producer": "home-assistant-packet-capture",
            "request_url": SENTINEL_URL,
            "timestamp": _utc_timestamp(),
        }
        with records_lock:
            _write_artifact()
    except Exception:
        # The probe treats a missing producer sentinel as producer failure. This
        # sidecar keeps running so later traffic is still visible for diagnosis.
        pass


def _record_request_line(method: str, target: str) -> None:
    global current_record
    record = {
        "timestamp": _utc_timestamp(),
        "method": method,
        "path": target,
        "scheme": "http",
    }
    current_record = record
    _append_record(record)


def _consume_tcpdump(stdout) -> None:
    for raw_line in stdout:
        line = raw_line.strip()
        match = REQUEST_LINE_RE.match(line)
        if match:
            _record_request_line(match.group(1), match.group(2))
            continue
        if line.lower().startswith("host:"):
            _update_current_host(line.split(":", 1)[1].strip())


def _shutdown(_signum, _frame) -> None:
    if tcpdump_process is not None and tcpdump_process.poll() is None:
        tcpdump_process.terminate()
        try:
            tcpdump_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tcpdump_process.kill()
    with records_lock:
        _write_artifact()
    raise SystemExit(0)


def main() -> int:
    global tcpdump_process
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    with records_lock:
        _write_artifact()
    tcpdump_process = subprocess.Popen(
        ["tcpdump", "-i", INTERFACE, "-l", "-A", "-s", "0", CAPTURE_FILTER],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    threading.Thread(target=_send_sentinel_request, daemon=True).start()
    assert tcpdump_process.stdout is not None
    _consume_tcpdump(tcpdump_process.stdout)
    return tcpdump_process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
