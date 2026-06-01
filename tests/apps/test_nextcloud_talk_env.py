import importlib.util
import shutil
import sys
from pathlib import Path


def test_nextcloud_talk_loads_benchmark_env_without_dotenv(monkeypatch, tmp_path):
    app_dir = Path(__file__).resolve().parents[2] / "apps" / "nextcloud-talk"
    for name in ("common_setup.py", "metadata.json", "benchmark.env"):
        shutil.copy2(app_dir / name, tmp_path / name)

    assert not (tmp_path / ".env").exists()

    for key in (
        "ADMIN_USERNAME",
        "ADMIN_PASSWORD",
        "USER_A_USERNAME",
        "USER_A_PASSWORD",
        "USER_B_USERNAME",
        "USER_B_PASSWORD",
        "USER_B_EMAIL",
        "USER_B_MESSAGE",
        "ADMIN_FILE_CONTENTS",
        "ADMIN_FILE_NAME",
        "USER_B_FILE_CONTENTS",
        "USER_B_FILE_NAME",
    ):
        monkeypatch.delenv(key, raising=False)

    spec = importlib.util.spec_from_file_location(
        "test_nextcloud_talk_common_setup", tmp_path / "common_setup.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules["test_nextcloud_talk_common_setup"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("test_nextcloud_talk_common_setup", None)

    assert module.ENV_PATH.resolve() == (tmp_path / "benchmark.env").resolve()
    assert module.ADMIN_USERNAME == "admin"
    assert module.USER_A_USERNAME == "user_a"
