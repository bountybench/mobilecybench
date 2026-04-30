from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "apps" / "jerboa" / "jerboa_probe_utils.py"
)
_SPEC = importlib.util.spec_from_file_location("jerboa_probe_utils", _MODULE_PATH)
assert _SPEC and _SPEC.loader
jerboa_probe_utils = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(jerboa_probe_utils)


def test_get_lemmy_direct_base_url_prefers_container_ip(monkeypatch):
    monkeypatch.setenv("LEMMY_URL", "https://localhost:8536")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="172.19.0.4\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert jerboa_probe_utils.get_lemmy_direct_base_url() == "http://172.19.0.4:8536"


def test_get_lemmy_direct_base_url_falls_back_to_proxy(monkeypatch):
    monkeypatch.setenv("LEMMY_URL", "https://localhost:8536")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, stdout="", stderr="not found")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert jerboa_probe_utils.get_lemmy_direct_base_url() == "https://localhost:8536"
