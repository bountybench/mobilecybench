import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_bash(
    script: str, *, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env["ROOT_DIR"] = str(REPO_ROOT)
    if env:
        merged_env.update(env)
    return subprocess.run(
        ["bash", "-lc", script],
        cwd=REPO_ROOT,
        env=merged_env,
        capture_output=True,
        text=True,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _write_executable(path: Path, content: str) -> None:
    _write(path, content)
    path.chmod(0o755)


def _write_task_metadata(task_dir: Path, metadata: dict) -> None:
    _write(task_dir / "metadata.json", json.dumps(metadata, indent=2) + "\n")
    _write(task_dir / "fix.patch", "diff --git a/TODO b/TODO\n")
    _write_executable(
        task_dir / "verify_files" / "verify_exploit.sh",
        "#!/usr/bin/env bash\nexit 0\n",
    )


def _base_metadata(*, attack_model: str) -> dict:
    return {
        "schema_version": 1,
        "task_id": "demo_task",
        "title": "Demo task",
        "attack_model": attack_model,
        "baseline": {"commit": "deadbeef"},
        "runtime": {"package_name": "com.example.target"},
    }


def test_source_validation_accepts_malicious_apk_task(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    _write_task_metadata(task_dir, _base_metadata(attack_model="malicious_apk"))
    _write(
        task_dir / "exploit_files" / "exploit_apk" / "AndroidManifest.xml",
        "<manifest/>\n",
    )
    _write(
        task_dir
        / "exploit_files"
        / "exploit_apk"
        / "src"
        / "com"
        / "mobilecybench"
        / "exploit"
        / "Exploit.java",
        "class Exploit {}\n",
    )

    result = _run_bash(
        f'source "$ROOT_DIR/scripts/zero_day_task_common.sh"\nzero_day_task_validate_source_dir "{task_dir}"'
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_source_validation_accepts_auth_attacker_task(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    _write_task_metadata(task_dir, _base_metadata(attack_model="auth_attacker"))
    _write_executable(
        task_dir / "exploit_files" / "exploit.sh",
        "#!/usr/bin/env bash\nexit 0\n",
    )

    result = _run_bash(
        f'source "$ROOT_DIR/scripts/zero_day_task_common.sh"\nzero_day_task_validate_source_dir "{task_dir}"'
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_source_validation_rejects_mixed_exploit_artifacts(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    _write_task_metadata(task_dir, _base_metadata(attack_model="malicious_apk"))
    _write_executable(
        task_dir / "exploit_files" / "exploit.sh", "#!/usr/bin/env bash\nexit 0\n"
    )
    _write(
        task_dir / "exploit_files" / "exploit_apk" / "AndroidManifest.xml",
        "<manifest/>\n",
    )
    _write(
        task_dir / "exploit_files" / "exploit_apk" / "src" / "Exploit.java",
        "class Exploit {}\n",
    )

    result = _run_bash(
        f'source "$ROOT_DIR/scripts/zero_day_task_common.sh"\nzero_day_task_validate_source_dir "{task_dir}"'
    )

    assert result.returncode != 0
    assert "must not mix exploit_files/exploit.sh" in (result.stderr + result.stdout)


def test_source_validation_rejects_missing_attack_model(
    tmp_path: Path,
) -> None:
    task_dir = tmp_path / "task"
    metadata = _base_metadata(attack_model="malicious_apk")
    del metadata["attack_model"]
    _write_task_metadata(task_dir, metadata)
    _write(
        task_dir / "exploit_files" / "exploit_apk" / "AndroidManifest.xml",
        "<manifest/>\n",
    )
    _write(
        task_dir / "exploit_files" / "exploit_apk" / "src" / "Exploit.java",
        "class Exploit {}\n",
    )

    result = _run_bash(
        f'source "$ROOT_DIR/scripts/zero_day_task_common.sh"\nzero_day_task_validate_source_dir "{task_dir}"'
    )

    assert result.returncode != 0
    assert "must declare attack_model" in (result.stderr + result.stdout)


def test_source_validation_rejects_apk_task_without_java_sources(
    tmp_path: Path,
) -> None:
    task_dir = tmp_path / "task"
    _write_task_metadata(task_dir, _base_metadata(attack_model="malicious_apk"))
    _write(
        task_dir / "exploit_files" / "exploit_apk" / "AndroidManifest.xml",
        "<manifest/>\n",
    )

    result = _run_bash(
        f'source "$ROOT_DIR/scripts/zero_day_task_common.sh"\nzero_day_task_validate_source_dir "{task_dir}"'
    )

    assert result.returncode != 0
    assert "must contain at least one .java source file" in (
        result.stderr + result.stdout
    )


def test_resolve_metadata_rejects_missing_attack_model(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True)

    _write_task_metadata(
        task_dir,
        {
            "task_id": "compat_task",
            "title": "Compat task",
            "baseline": {"commit": "deadbeef"},
            "runtime": {"package_name": "com.example.target"},
        },
    )
    _write(
        task_dir / "exploit_files" / "exploit_apk" / "AndroidManifest.xml",
        "<manifest/>\n",
    )
    _write(
        task_dir / "exploit_files" / "exploit_apk" / "src" / "Exploit.java",
        "class Exploit {}\n",
    )
    _write(
        app_dir / "metadata.json",
        json.dumps({"package_name": "com.example.target"}) + "\n",
    )

    result = _run_bash(
        "\n".join(
            [
                'source "$ROOT_DIR/scripts/zero_day_task_common.sh"',
                f'zero_day_task_resolve_metadata "{task_dir}" "{app_dir}" "{task_dir}"',
            ]
        )
    )

    assert result.returncode != 0
    assert "must declare attack_model" in (result.stderr + result.stdout)


def _make_phase_fixture(
    tmp_path: Path, attack_model: str
) -> tuple[Path, Path, Path, Path, Path]:
    app_dir = tmp_path / "app"
    task_dir = tmp_path / "task"
    bin_dir = tmp_path / "bin"
    order_log = tmp_path / "order.log"
    output_dir = tmp_path / "output"
    logs_dir = tmp_path / "logs"
    artifacts_dir = tmp_path / "artifacts"
    workspace_dir = tmp_path / "workspace"

    app_dir.mkdir(parents=True)
    task_dir.mkdir(parents=True)
    bin_dir.mkdir(parents=True)
    output_dir.mkdir()
    logs_dir.mkdir()
    artifacts_dir.mkdir()
    workspace_dir.mkdir()

    _write(app_dir / "metadata.json", "{}\n")
    _write_executable(
        app_dir / "start_runtime.sh",
        "#!/usr/bin/env bash\n" 'echo "start_runtime:$*" >> "$ORDER_LOG"\n',
    )
    _write_executable(
        app_dir / "prepare_victim.sh",
        "#!/usr/bin/env bash\n" 'echo "prepare_victim" >> "$ORDER_LOG"\n',
    )

    _write(
        task_dir / "metadata.json",
        json.dumps(_base_metadata(attack_model=attack_model)) + "\n",
    )
    _write(task_dir / "fix.patch", "diff --git a/TODO b/TODO\n")
    _write_executable(
        task_dir / "prepare_app.sh",
        "#!/usr/bin/env bash\n" 'echo "prepare_app" >> "$ORDER_LOG"\n',
    )
    _write_executable(
        task_dir / "verify_files" / "verify_exploit.sh",
        "#!/usr/bin/env bash\n" 'echo "verify" >> "$ORDER_LOG"\n' "exit 0\n",
    )

    if attack_model == "auth_attacker":
        _write_executable(
            task_dir / "exploit_files" / "exploit.sh", "#!/usr/bin/env bash\nexit 0\n"
        )
    else:
        _write(
            task_dir / "exploit_files" / "exploit_apk" / "AndroidManifest.xml",
            "<manifest/>\n",
        )
        _write(
            task_dir / "exploit_files" / "exploit_apk" / "src" / "Exploit.java",
            "class Exploit {}\n",
        )

    _write_executable(
        bin_dir / "adb",
        "#!/usr/bin/env bash\n"
        'echo "adb:$*" >> "$ORDER_LOG"\n'
        'if [[ "$1" == "shell" && "$2" == "pm" && "$3" == "list" && "$4" == "packages" ]]; then\n'
        '  echo "package:${TARGET_PACKAGE}"\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "$1" == "shell" && "$2" == "pm" && "$3" == "clear" ]]; then\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
    )

    env = {
        "ORDER_LOG": str(order_log),
        "TARGET_PACKAGE": "com.example.target",
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }
    return (
        app_dir,
        task_dir,
        output_dir,
        logs_dir,
        artifacts_dir,
        workspace_dir,
        order_log,
        env,
    )


def _phase_script(
    app_dir: Path,
    task_dir: Path,
    output_dir: Path,
    logs_dir: Path,
    artifacts_dir: Path,
    workspace_dir: Path,
    attack_model: str,
) -> str:
    return "\n".join(
        [
            'source "$ROOT_DIR/scripts/task_validation_common.sh"',
            'task_runtime_run_exploit_apk() { echo "exploit_apk" >> "$ORDER_LOG"; return 0; }',
            'task_runtime_run_exploit_container() { echo "exploit_container" >> "$ORDER_LOG"; return 0; }',
            (
                "task_validation_set_context "
                f'"$ROOT_DIR" "{app_dir}" "{task_dir}" "{output_dir}" '
                f'"{logs_dir}" "{artifacts_dir}" "com.example.target" '
                f'"demo_task" "deadbeef" "{attack_model}" "{task_dir / "fix.patch"}" '
                f'"{workspace_dir}" "per_phase" "false"'
            ),
            'task_validation_run_phase "Vulnerable build" "vulnerable" "" "true"',
        ]
    )


def test_malicious_apk_phase_runs_victim_setup_before_exploit(tmp_path: Path) -> None:
    (
        app_dir,
        task_dir,
        output_dir,
        logs_dir,
        artifacts_dir,
        workspace_dir,
        order_log,
        env,
    ) = _make_phase_fixture(tmp_path, "malicious_apk")

    result = _run_bash(
        _phase_script(
            app_dir,
            task_dir,
            output_dir,
            logs_dir,
            artifacts_dir,
            workspace_dir,
            "malicious_apk",
        ),
        env=env,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    lines = [
        line.strip() for line in order_log.read_text().splitlines() if line.strip()
    ]
    assert (
        lines.index("prepare_app")
        < lines.index("prepare_victim")
        < lines.index("exploit_apk")
        < lines.index("verify")
    )


def test_auth_attacker_phase_clears_app_before_victim_setup(tmp_path: Path) -> None:
    (
        app_dir,
        task_dir,
        output_dir,
        logs_dir,
        artifacts_dir,
        workspace_dir,
        order_log,
        env,
    ) = _make_phase_fixture(tmp_path, "auth_attacker")

    result = _run_bash(
        _phase_script(
            app_dir,
            task_dir,
            output_dir,
            logs_dir,
            artifacts_dir,
            workspace_dir,
            "auth_attacker",
        ),
        env=env,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    lines = [
        line.strip() for line in order_log.read_text().splitlines() if line.strip()
    ]
    clear_line = "adb:shell pm clear com.example.target"
    assert (
        lines.index("prepare_app")
        < lines.index("exploit_container")
        < lines.index(clear_line)
        < lines.index("prepare_victim")
        < lines.index("verify")
    )
