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


def _base_metadata(*, attacker_model: str) -> dict:
    return {
        "schema_version": 1,
        "task_id": "demo_task",
        "title": "Demo task",
        "attacker_model": attacker_model,
        "baseline": {"commit": "deadbeef"},
        "runtime": {"package_name": "com.example.target"},
    }


def test_source_validation_accepts_malicious_app_task(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    _write_task_metadata(task_dir, _base_metadata(attacker_model="malicious_app"))
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


def test_source_validation_accepts_remote_attacker_task(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    _write_task_metadata(task_dir, _base_metadata(attacker_model="remote_attacker"))
    _write_executable(
        task_dir / "exploit_files" / "exploit.sh",
        "#!/usr/bin/env bash\nexit 0\n",
    )

    result = _run_bash(
        f'source "$ROOT_DIR/scripts/zero_day_task_common.sh"\nzero_day_task_validate_source_dir "{task_dir}"'
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_task_runtime_run_exploit_apk_injects_default_build_script(
    tmp_path: Path,
) -> None:
    task_dir = tmp_path / "task"
    apk_dir = task_dir / "exploit_files" / "exploit_apk"
    output_dir = tmp_path / "output"
    bin_dir = tmp_path / "bin"

    _write(apk_dir / "AndroidManifest.xml", "<manifest/>\n")
    _write(apk_dir / "src" / "Exploit.java", "class Exploit {}\n")
    output_dir.mkdir(parents=True, exist_ok=True)
    bin_dir.mkdir(parents=True, exist_ok=True)
    _write_executable(
        bin_dir / "python3",
        """#!/usr/bin/env bash
set -euo pipefail
test -f "$3/build_exploit_apk.sh"
test -x "$3/build_exploit_apk.sh"
cmp "$2/templates/malicious_app/build_exploit_apk.sh" "$3/build_exploit_apk.sh" >/dev/null
exit 0
""",
    )

    result = _run_bash(
        "\n".join(
            [
                'source "$ROOT_DIR/scripts/task_runtime_common.sh"',
                f'export PATH="{bin_dir}:{os.environ["PATH"]}"',
                f'TASK_RUNTIME_TASK_DIR="{task_dir}"',
                f'TASK_RUNTIME_OUTPUT_DIR="{output_dir}"',
                "TASK_RUNTIME_ENV=()",
                'task_runtime_run_exploit_apk "$ROOT_DIR"',
            ]
        )
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert (apk_dir / "build_exploit_apk.sh").exists()


def test_source_validation_rejects_mixed_exploit_artifacts(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    _write_task_metadata(task_dir, _base_metadata(attacker_model="malicious_app"))
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


def test_source_validation_rejects_legacy_attack_model_field(
    tmp_path: Path,
) -> None:
    task_dir = tmp_path / "task"
    metadata = _base_metadata(attacker_model="malicious_app")
    metadata["attack_model"] = metadata.pop("attacker_model")
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
    assert "uses legacy attack_model" in (result.stderr + result.stdout)


def test_source_validation_rejects_missing_attacker_model(
    tmp_path: Path,
) -> None:
    task_dir = tmp_path / "task"
    metadata = _base_metadata(attacker_model="malicious_app")
    del metadata["attacker_model"]
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
    assert "must declare attacker_model" in (result.stderr + result.stdout)


def test_source_validation_rejects_apk_task_without_java_sources(
    tmp_path: Path,
) -> None:
    task_dir = tmp_path / "task"
    _write_task_metadata(task_dir, _base_metadata(attacker_model="malicious_app"))
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


def test_source_validation_rejects_legacy_attacker_app_dir(tmp_path: Path) -> None:
    task_dir = tmp_path / "task"
    _write_task_metadata(task_dir, _base_metadata(attacker_model="malicious_app"))
    _write(
        task_dir / "exploit_files" / "attacker_app" / "AndroidManifest.xml",
        "<manifest/>\n",
    )
    _write(
        task_dir / "exploit_files" / "attacker_app" / "src" / "Exploit.java",
        "class Exploit {}\n",
    )

    result = _run_bash(
        f'source "$ROOT_DIR/scripts/zero_day_task_common.sh"\nzero_day_task_validate_source_dir "{task_dir}"'
    )

    assert result.returncode != 0
    assert "Legacy exploit APK directory is not supported" in (
        result.stderr + result.stdout
    )


def test_resolve_metadata_rejects_missing_attacker_model(tmp_path: Path) -> None:
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
    assert "must declare attacker_model" in (result.stderr + result.stdout)


def test_task_validation_set_context_clears_state_on_invalid_args() -> None:
    result = _run_bash(
        "\n".join(
            [
                'source "$ROOT_DIR/scripts/task_validation_common.sh"',
                'TASK_VALIDATION_ATTACKER_MODEL="sentinel"',
                'TASK_VALIDATION_FIX_PATCH="/tmp/original.patch"',
                'TASK_VALIDATION_WORKSPACE_DIR="/tmp/original-workspace"',
                'TASK_VALIDATION_OUTPUT_MODE="flat"',
                'TASK_VALIDATION_RESET_FLAT_OUTPUT="true"',
                (
                    'task_validation_set_context "$ROOT_DIR" "/tmp/app" "/tmp/task" '
                    '"/tmp/output" "/tmp/logs" "/tmp/artifacts" "com.example.target" '
                    '"demo_task" "deadbeef" "/tmp/bad-shift.patch" "" "flat" "true"'
                ),
                "status=$?",
                'printf "status=%s\\nattacker_model=%s\\nfix_patch=%s\\nworkspace=%s\\noutput_mode=%s\\nreset=%s\\n" '
                '"$status" "$TASK_VALIDATION_ATTACKER_MODEL" "$TASK_VALIDATION_FIX_PATCH" '
                '"$TASK_VALIDATION_WORKSPACE_DIR" "$TASK_VALIDATION_OUTPUT_MODE" "$TASK_VALIDATION_RESET_FLAT_OUTPUT"',
            ]
        )
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "status=1" in result.stdout
    assert "attacker_model=" in result.stdout
    assert "fix_patch=" in result.stdout
    assert "workspace=" in result.stdout
    assert "output_mode=per_phase" in result.stdout
    assert "reset=false" in result.stdout
    assert "sentinel" not in result.stdout
    assert "/tmp/original.patch" not in result.stdout
    assert "/tmp/original-workspace" not in result.stdout


def test_task_validation_set_context_rejects_too_many_args() -> None:
    result = _run_bash(
        "\n".join(
            [
                'source "$ROOT_DIR/scripts/task_validation_common.sh"',
                (
                    'task_validation_set_context "$ROOT_DIR" "/tmp/app" "/tmp/task" '
                    '"/tmp/output" "/tmp/logs" "/tmp/artifacts" "com.example.target" '
                    '"demo_task" "deadbeef" "" "" "" "flat" "false" "extra"'
                ),
            ]
        )
    )

    assert result.returncode != 0
    assert "expected 9-14 args" in (result.stderr + result.stdout)


def test_zero_day_validation_passes_explicit_hardened_output_for_local_task(
    tmp_path: Path,
) -> None:
    root_dir = tmp_path / "root"
    app_name = "demoapp"
    app_dir = root_dir / "apps" / app_name
    task_dir = app_dir / "zero_day_vulnerabilities" / "demo_task"
    trace_file = tmp_path / "trace.log"

    root_dir.mkdir(parents=True, exist_ok=True)
    (root_dir / "scripts").symlink_to(REPO_ROOT / "scripts")
    (root_dir / "templates").symlink_to(REPO_ROOT / "templates")
    _write(
        root_dir / "zero_day_task_bundle_schema.json",
        (REPO_ROOT / "zero_day_task_bundle_schema.json").read_text(),
    )

    app_dir.mkdir(parents=True, exist_ok=True)
    _write(
        app_dir / "metadata.json",
        json.dumps({"package_name": "com.example.target"}) + "\n",
    )
    _write_task_metadata(task_dir, _base_metadata(attacker_model="malicious_app"))
    _write(
        task_dir / "exploit_files" / "exploit_apk" / "AndroidManifest.xml",
        "<manifest/>\n",
    )
    _write(
        task_dir / "exploit_files" / "exploit_apk" / "src" / "Exploit.java",
        "class Exploit {}\n",
    )

    script = "\n".join(
        [
            f'REAL_ROOT="{REPO_ROOT}"',
            f'ROOT_DIR="{root_dir}"',
            'source "$ROOT_DIR/scripts/zero_day_task_common.sh"',
            "task_validation_resolve_android_serial() { return 0; }",
            'task_validation_set_context() { echo "set_context:$*" >> "$TRACE_FILE"; return 0; }',
            'task_validation_run_phase() { echo "run_phase:$*" >> "$TRACE_FILE"; return 0; }',
            'task_validation_cleanup_runtime() { echo "cleanup" >> "$TRACE_FILE"; return 0; }',
            'zero_day_task_run_build() { echo "build:$*" >> "$TRACE_FILE"; return 0; }',
            f'zero_day_task_run_validation "{app_name}" "{task_dir}" false "" false',
        ]
    )

    result = _run_bash(
        script,
        env={"TRACE_FILE": str(trace_file)},
    )

    assert result.returncode == 0, result.stderr or result.stdout
    lines = [
        line.strip() for line in trace_file.read_text().splitlines() if line.strip()
    ]
    secure_build = next(line for line in lines if line.startswith("build:"))
    assert "--output" in secure_build
    assert str(task_dir.parent / "artifacts" / "demo_task" / "hardened_apk") in secure_build
    assert "--hardened-patch" in secure_build


def _make_phase_fixture(
    tmp_path: Path, attacker_model: str
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
        json.dumps(_base_metadata(attacker_model=attacker_model)) + "\n",
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

    if attacker_model == "remote_attacker":
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
    attacker_model: str,
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
                f'"demo_task" "deadbeef" "{attacker_model}" "{task_dir / "fix.patch"}" '
                f'"{workspace_dir}" "per_phase" "false"'
            ),
            'task_validation_run_phase "Vulnerable build" "vulnerable" "" "true"',
        ]
    )


def test_malicious_app_phase_runs_victim_setup_before_exploit(tmp_path: Path) -> None:
    (
        app_dir,
        task_dir,
        output_dir,
        logs_dir,
        artifacts_dir,
        workspace_dir,
        order_log,
        env,
    ) = _make_phase_fixture(tmp_path, "malicious_app")

    result = _run_bash(
        _phase_script(
            app_dir,
            task_dir,
            output_dir,
            logs_dir,
            artifacts_dir,
            workspace_dir,
            "malicious_app",
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


def test_remote_attacker_phase_clears_app_before_victim_setup(tmp_path: Path) -> None:
    (
        app_dir,
        task_dir,
        output_dir,
        logs_dir,
        artifacts_dir,
        workspace_dir,
        order_log,
        env,
    ) = _make_phase_fixture(tmp_path, "remote_attacker")

    result = _run_bash(
        _phase_script(
            app_dir,
            task_dir,
            output_dir,
            logs_dir,
            artifacts_dir,
            workspace_dir,
            "remote_attacker",
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
