"""Tests for the replay_apk.sh script and run_exploit_container.sh --exec-script param."""

import subprocess

import pytest


class TestReplayApkScript:
    """Behavioral tests for utils/replay_apk.sh (syntax and structure)."""

    def test_script_has_valid_bash_syntax(self):
        """replay_apk.sh must pass bash -n syntax check."""
        result = subprocess.run(
            ["bash", "-n", "utils/replay_apk.sh"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    def test_script_is_executable(self):
        import os

        assert os.access("utils/replay_apk.sh", os.X_OK)

    def test_script_uses_set_euo_pipefail(self):
        with open("utils/replay_apk.sh") as f:
            content = f.read()
        assert "set -euo pipefail" in content

    def test_script_builds_before_install(self):
        """Build, install, instrument must appear in correct order (non-comment lines)."""
        with open("utils/replay_apk.sh") as f:
            lines = [l for l in f if not l.strip().startswith("#")]
        content = "\n".join(lines)
        build_pos = content.index("build.sh")
        install_pos = content.index("adb install")
        instrument_pos = content.index("am instrument")
        assert build_pos < install_pos < instrument_pos

    def test_script_captures_logcat(self):
        with open("utils/replay_apk.sh") as f:
            content = f.read()
        assert "MOBILECYBENCH" in content
        assert "logcat" in content

    def test_script_parses_instrumentation_code(self):
        with open("utils/replay_apk.sh") as f:
            content = f.read()
        assert "INSTRUMENTATION_CODE" in content

    def test_script_uses_timeout(self):
        with open("utils/replay_apk.sh") as f:
            content = f.read()
        assert "timeout" in content


class TestRunExploitContainerExecScript:
    """Tests for --exec-script param in run_exploit_container.sh."""

    def test_script_has_valid_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", "utils/run_exploit_container.sh"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    def test_exec_script_default_is_exploit_sh(self):
        with open("utils/run_exploit_container.sh") as f:
            content = f.read()
        assert 'exec_script="/app/agent_exploit/exploit.sh"' in content

    def test_exec_script_param_in_arg_parser(self):
        with open("utils/run_exploit_container.sh") as f:
            content = f.read()
        assert "--exec-script)" in content

    def test_exec_script_used_in_docker_exec(self):
        """The exec_script variable must be used in the docker exec command."""
        with open("utils/run_exploit_container.sh") as f:
            content = f.read()
        assert 'bash "$exec_script"' in content

    def test_exec_script_documented_in_usage(self):
        with open("utils/run_exploit_container.sh") as f:
            content = f.read()
        # Extract the usage() heredoc (between usage() and the closing })
        usage_start = content.index("usage()")
        usage_end = content.index("\n}", usage_start)
        usage_section = content[usage_start:usage_end]
        assert "--exec-script" in usage_section


class TestBuildShTemplate:
    """Tests for the APK build template."""

    def test_build_sh_has_valid_bash_syntax(self):
        result = subprocess.run(
            ["bash", "-n", "utils/malicious_apk_template/build.sh"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    def test_build_sh_is_executable(self):
        import os

        assert os.access("utils/malicious_apk_template/build.sh", os.X_OK)

    def test_build_sh_outputs_correct_apk_name(self):
        with open("utils/malicious_apk_template/build.sh") as f:
            content = f.read()
        assert "com.mobilecybench.apk" in content

    def test_build_sh_signs_apk(self):
        with open("utils/malicious_apk_template/build.sh") as f:
            content = f.read()
        assert "apksigner" in content.lower() or "APKSIGNER" in content

    def test_build_sh_requires_android_home(self):
        with open("utils/malicious_apk_template/build.sh") as f:
            content = f.read()
        assert "ANDROID_HOME" in content


class TestManifestTemplate:
    """Tests for the AndroidManifest.xml template."""

    def test_manifest_declares_package(self):
        with open("utils/malicious_apk_template/AndroidManifest.xml") as f:
            content = f.read()
        assert 'package="com.mobilecybench"' in content

    def test_manifest_declares_instrumentation(self):
        with open("utils/malicious_apk_template/AndroidManifest.xml") as f:
            content = f.read()
        assert "ExploitRunner" in content
        assert 'android:targetPackage="com.mobilecybench"' in content


class TestExploitRunnerTemplate:
    """Tests for the ExploitRunner.java template."""

    def test_has_correct_package(self):
        with open(
            "utils/malicious_apk_template/src/com/mobilecybench/ExploitRunner.java"
        ) as f:
            content = f.read()
        assert "package com.mobilecybench;" in content

    def test_extends_instrumentation(self):
        with open(
            "utils/malicious_apk_template/src/com/mobilecybench/ExploitRunner.java"
        ) as f:
            content = f.read()
        assert "extends Instrumentation" in content

    def test_calls_finish_with_code(self):
        with open(
            "utils/malicious_apk_template/src/com/mobilecybench/ExploitRunner.java"
        ) as f:
            content = f.read()
        assert "finish(code, result)" in content

    def test_has_exploit_method(self):
        with open(
            "utils/malicious_apk_template/src/com/mobilecybench/ExploitRunner.java"
        ) as f:
            content = f.read()
        assert "private boolean exploit()" in content

    def test_success_maps_to_zero(self):
        with open(
            "utils/malicious_apk_template/src/com/mobilecybench/ExploitRunner.java"
        ) as f:
            content = f.read()
        assert "success ? 0 : 1" in content

    def test_logs_with_mobilecybench_tag(self):
        with open(
            "utils/malicious_apk_template/src/com/mobilecybench/ExploitRunner.java"
        ) as f:
            content = f.read()
        assert 'TAG = "MOBILECYBENCH"' in content
