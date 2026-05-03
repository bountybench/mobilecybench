from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MOEMEMOS_DIR = REPO_ROOT / "apps" / "moememos"


def test_start_runtime_does_not_rewrite_exploit_script():
    start_runtime = (MOEMEMOS_DIR / "start_runtime.sh").read_text(encoding="utf-8")

    assert "HOST_IP_PLACEHOLDER" not in start_runtime
    assert "sed -i" not in start_runtime
    assert "configure_exploit_host_ip" not in start_runtime


def test_start_runtime_restores_non_root_adb_shell_after_hydration():
    start_runtime = (MOEMEMOS_DIR / "start_runtime.sh").read_text(encoding="utf-8")

    assert "restore_adb_user_shell" in start_runtime
    assert "adb unroot" in start_runtime
    assert "wait_for_adb_shell_ready 90" in start_runtime
    assert "uid=0" in start_runtime


def test_remote_attacker_exploit_uses_emulator_token_catcher_url():
    exploit = (
        MOEMEMOS_DIR
        / "synthetic_vulnerabilities"
        / "vuln_0"
        / "exploit_files"
        / "exploit.sh"
    ).read_text(encoding="utf-8")

    assert "HOST_IP_PLACEHOLDER" not in exploit
    assert "hostname -I" not in exploit
    assert "MOEMEMOS_EMULATOR_TOKEN_CATCHER_URL" in exploit
    assert "http://127.0.0.1:8082" in exploit
    assert "MALICIOUS_IMAGE_URL" in exploit


def test_remote_attacker_verifier_refreshes_token_catcher_adb_reverse():
    verifier = (
        MOEMEMOS_DIR
        / "synthetic_vulnerabilities"
        / "vuln_0"
        / "verify_files"
        / "verify_exploit.sh"
    ).read_text(encoding="utf-8")

    assert "ensure_token_catcher_reverse" in verifier
    assert 'adb reverse "tcp:${TOKEN_CATCHER_REVERSE_EMULATOR_PORT}"' in verifier
    assert "MOEMEMOS_TOKEN_CATCHER_HOST_PORT" in verifier
