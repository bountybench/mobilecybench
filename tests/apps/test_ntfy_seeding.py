import importlib.util
import sys
from pathlib import Path


def _load_ntfy_module(module_name: str):
    module_path = (
        Path(__file__).resolve().parents[2]
        / "apps"
        / "ntfy-android"
        / "ntfy_seeding.py"
    )
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def test_ntfy_seeding_loads_dotenv_relative_to_script(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for key in (
        "NTFY_URL",
        "EMULATOR_GATEWAY",
        "SEED_OUTPUT_FILE",
        "ACCESS_CONTROL_BASELINE",
        "SECRETS_FILE",
        "SERVER_READY_TIMEOUT",
        "SEED_LOG_FILE",
    ):
        monkeypatch.delenv(key, raising=False)

    module = _load_ntfy_module("test_ntfy_seeding_relpath")

    assert module.NTFY_URL == "http://localhost:8080"
    assert module.EMULATOR_GATEWAY == "http://10.0.2.2:8080"
    assert module.OUTPUT_FILE == "baseline_manifest.json"
    assert module.ACCESS_CONTROL_BASELINE == "baseline_access_control.json"
    assert module.SECRETS_FILE == "secrets.json"
    assert module.SERVER_TIMEOUT == 30
    assert module.LOG_FILE == "ntfy_seeding.log"
