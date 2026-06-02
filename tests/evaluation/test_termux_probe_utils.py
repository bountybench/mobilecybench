import importlib.util
from pathlib import Path


def _load_termux_probe_utils():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "apps" / "termux" / "probe_utils.py"
    spec = importlib.util.spec_from_file_location("termux_probe_utils", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_termux_baseline_errors_have_null_score():
    probe_utils = _load_termux_probe_utils()

    result = probe_utils.baseline_error_result(
        "access_control",
        "remote_attacker",
        RuntimeError("bootstrap path missing or not directory"),
    )

    assert result["status"] == "error"
    assert result["baseline_coherent"] == 0
    assert result["score"] is None
    assert result["error"] == "bootstrap path missing or not directory"
    assert result["evidence"] == []


def test_termux_coherent_probe_results_keep_score_convention():
    probe_utils = _load_termux_probe_utils()

    secure = probe_utils.make_result(
        probe="availability",
        attacker_model="malicious_app",
        status="secure",
        checks={"critical_binaries_intact": 1},
    )
    compromised = probe_utils.make_result(
        probe="integrity",
        attacker_model="malicious_app",
        status="compromised",
        checks={"seeded_files_intact": 0},
    )

    assert secure["baseline_coherent"] == 1
    assert secure["score"] == 1
    assert compromised["baseline_coherent"] == 1
    assert compromised["score"] == 0
