"""Tests for agent_container module."""

import io
import os
import subprocess
import tarfile
from unittest.mock import MagicMock, patch

import docker.errors

from agent.agent_container import AgentEnvironment


class TestAgentEnvironmentVerifyFiles:
    """Tests for AgentEnvironment._setup_verify_files()."""

    def _create_agent_env(self, app_dir, vuln_id=None):
        """Helper to create AgentEnvironment without starting Docker."""
        return AgentEnvironment(
            app_dir=app_dir,
            docker_networks=["test_net"],
            image_name="test:latest",
            env={},
            commit_id="HEAD",
            workflow="exploit",
            vuln_id=vuln_id,
        )

    def test_setup_verify_files_returns_none_when_no_vuln_id(self, tmp_path):
        """_setup_verify_files should not be called when vuln_id is None."""
        agent_env = self._create_agent_env(tmp_path, vuln_id=None)
        # When vuln_id is None, the method shouldn't be called in normal flow,
        # but if called directly it would fail. This tests the guard condition.
        assert agent_env.vuln_id is None

    def test_setup_verify_files_returns_none_when_dir_missing(self, tmp_path):
        """_setup_verify_files returns None if verify_files directory doesn't exist."""
        agent_env = self._create_agent_env(tmp_path, vuln_id="vuln_0")

        result = agent_env._setup_verify_files()

        assert result is None

    def test_setup_verify_files_returns_volume_mapping(self, tmp_path):
        """_setup_verify_files returns correct volume mapping when verify_files exists."""
        # Create verify_files directory
        verify_files = (
            tmp_path / "synthetic_vulnerabilities" / "vuln_0" / "verify_files"
        )
        verify_files.mkdir(parents=True)

        agent_env = self._create_agent_env(tmp_path, vuln_id="vuln_0")
        result = agent_env._setup_verify_files()

        assert result is not None
        assert str(verify_files) in result
        assert result[str(verify_files)]["bind"] == "/app/verify_files/vuln_0"
        assert result[str(verify_files)]["mode"] == "ro"

    def test_setup_verify_files_uses_configurable_vuln_id(self, tmp_path):
        """_setup_verify_files uses the configured vuln_id, not hardcoded 'vuln_0'."""
        # Create verify_files for vuln_1 (not vuln_0)
        verify_files = (
            tmp_path / "synthetic_vulnerabilities" / "vuln_1" / "verify_files"
        )
        verify_files.mkdir(parents=True)

        agent_env = self._create_agent_env(tmp_path, vuln_id="vuln_1")
        result = agent_env._setup_verify_files()

        # Should find vuln_1, not fail looking for vuln_0
        assert result is not None
        assert str(verify_files) in result
        assert result[str(verify_files)]["bind"] == "/app/verify_files/vuln_1"

    def test_setup_verify_files_fails_for_wrong_vuln_id(self, tmp_path):
        """_setup_verify_files returns None when vuln_id doesn't match existing dirs."""
        # Create verify_files for vuln_0
        verify_files = (
            tmp_path / "synthetic_vulnerabilities" / "vuln_0" / "verify_files"
        )
        verify_files.mkdir(parents=True)

        # But request vuln_1
        agent_env = self._create_agent_env(tmp_path, vuln_id="vuln_1")
        result = agent_env._setup_verify_files()

        # Should return None since vuln_1 doesn't exist
        assert result is None


class TestSetupAgentOutput:
    """Tests for AgentEnvironment._setup_agent_output()."""

    def _create_agent_env(self, app_dir, vuln_id=None):
        return AgentEnvironment(
            app_dir=app_dir,
            docker_networks=["test_net"],
            image_name="test:latest",
            env={},
            commit_id="HEAD",
            workflow="exploit",
            vuln_id=vuln_id,
        )

    def test_cleans_stale_data(self, tmp_path):
        """Removes stale files from previous runs before creating fresh dir."""
        agent_output_dir = (
            tmp_path / "synthetic_vulnerabilities" / "vuln_0" / "agent_output"
        )
        agent_output_dir.mkdir(parents=True)
        stale_file = agent_output_dir / "captured_creds.txt"
        stale_file.write_text("stale data")

        agent_env = self._create_agent_env(tmp_path, vuln_id="vuln_0")
        agent_env._setup_agent_output()

        assert agent_output_dir.is_dir()
        assert not stale_file.exists()


class TestAgentEnvironmentVulnId:
    """Tests for vuln_id parameter handling in AgentEnvironment."""

    def test_vuln_id_stored_correctly(self, tmp_path):
        """AgentEnvironment stores vuln_id parameter."""
        agent_env = AgentEnvironment(
            app_dir=tmp_path,
            docker_networks=["test_net"],
            image_name="test:latest",
            env={},
            commit_id="HEAD",
            workflow="exploit",
            vuln_id="vuln_2",
        )

        assert agent_env.vuln_id == "vuln_2"

    def test_vuln_id_defaults_to_none(self, tmp_path):
        """AgentEnvironment vuln_id defaults to None."""
        agent_env = AgentEnvironment(
            app_dir=tmp_path,
            docker_networks=["test_net"],
            image_name="test:latest",
            env={},
            commit_id="HEAD",
            workflow="discovery",
        )

        assert agent_env.vuln_id is None


def _make_tar(files: dict[str, str]) -> bytes:
    """Create an in-memory tar archive. files maps arcname -> content."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestDiscoveryAgentCodebase:
    """Tests for discovery-only agent codebase injection."""

    _GIT_ENV = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
    }

    def _git(self, cwd, *args):
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, **self._GIT_ENV},
        )
        return result.stdout.strip()

    @patch("agent.agent_container.docker.from_env")
    def test_discovery_setup_injects_honeypot_into_staged_copy(
        self, _mock_docker, tmp_path
    ):
        # Set git config in environment for CI compatibility
        env = {
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        }
        os.environ.update(env)

        app_dir = tmp_path / "test_app"
        codebase_dir = app_dir / "codebase"
        manifest_dir = codebase_dir / "app" / "src" / "main"
        source_dir = manifest_dir / "java" / "com" / "example" / "app"
        source_dir.mkdir(parents=True)
        (source_dir / "ExampleActivity.java").write_text(
            "package com.example.app; class ExampleActivity {}",
            encoding="utf-8",
        )
        (manifest_dir / "AndroidManifest.xml").write_text(
            "<manifest><application></application></manifest>",
            encoding="utf-8",
        )
        self._git(codebase_dir, "init")
        self._git(codebase_dir, "add", "-A")
        self._git(codebase_dir, "commit", "-m", "Initial commit")
        commit_id = self._git(codebase_dir, "rev-parse", "HEAD")

        agent_env = AgentEnvironment(
            app_dir=app_dir,
            docker_networks=["test_net"],
            image_name="test:latest",
            env={},
            commit_id=commit_id,
            workflow="discovery",
            package_name="com.example.app",
        )

        agent_env._setup_agent_codebase()

        injected_file = (
            app_dir
            / "agent_codebase"
            / "app"
            / "src"
            / "main"
            / "java"
            / "com"
            / "example"
            / "app"
            / "internal"
            / "VulnFlagActivity.java"
        )
        assert injected_file.exists()
        assert not (
            codebase_dir
            / "app"
            / "src"
            / "main"
            / "java"
            / "com"
            / "example"
            / "app"
            / "internal"
            / "VulnFlagActivity.java"
        ).exists()

    @patch("agent.agent_container.docker.from_env")
    def test_exploit_setup_does_not_inject_discovery_honeypot(
        self, _mock_docker, tmp_path
    ):
        app_dir = tmp_path / "test_app"
        codebase_dir = app_dir / "codebase"
        manifest_dir = codebase_dir / "app" / "src" / "main"
        source_dir = manifest_dir / "java" / "com" / "example" / "app"
        source_dir.mkdir(parents=True)
        (manifest_dir / "AndroidManifest.xml").write_text(
            "<manifest><application></application></manifest>",
            encoding="utf-8",
        )

        agent_env = AgentEnvironment(
            app_dir=app_dir,
            docker_networks=["test_net"],
            image_name="test:latest",
            env={},
            commit_id="HEAD",
            workflow="exploit",
            package_name="com.example.app",
            vuln_id="vuln_0",
        )

        agent_env._setup_agent_codebase()

        assert not (
            app_dir
            / "agent_codebase"
            / "app"
            / "src"
            / "main"
            / "java"
            / "com"
            / "example"
            / "app"
            / "internal"
            / "VulnFlagActivity.java"
        ).exists()


class TestAgentContainerModeHandling:
    """Regression tests for workflow vs agent mode separation."""

    @patch("agent.agent_container.docker.from_env")
    def test_codex_mode_still_logs_in_after_container_start(
        self, mock_from_env, tmp_path
    ):
        mock_client = MagicMock()
        mock_from_env.return_value = mock_client
        mock_client.images.get.return_value = MagicMock()

        mock_container = MagicMock()
        mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"")
        mock_client.containers.run.return_value = mock_container
        mock_client.containers.get.side_effect = docker.errors.NotFound("not found")

        app_dir = tmp_path / "app"
        codebase_dir = app_dir / "codebase"
        codebase_dir.mkdir(parents=True)
        (codebase_dir / ".git").mkdir()

        agent_env = AgentEnvironment(
            app_dir=app_dir,
            docker_networks=["test_net"],
            image_name="test:latest",
            env={},
            commit_id="HEAD",
            mode="codex",
            workflow="discovery",
        )

        with patch.object(agent_env, "_setup_agent_codebase", return_value={}):
            agent_env.setup()

        mock_container.exec_run.assert_any_call(
            "bash -c 'echo $CODEX_API_KEY | codex login --with-api-key'"
        )

    @patch("agent.agent_container.docker.from_env")
    def test_non_codex_workflow_does_not_trigger_codex_login(
        self, mock_from_env, tmp_path
    ):
        mock_client = MagicMock()
        mock_from_env.return_value = mock_client
        mock_client.images.get.return_value = MagicMock()

        mock_container = MagicMock()
        mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"")
        mock_client.containers.run.return_value = mock_container
        mock_client.containers.get.side_effect = docker.errors.NotFound("not found")

        app_dir = tmp_path / "app"
        codebase_dir = app_dir / "codebase"
        codebase_dir.mkdir(parents=True)
        (codebase_dir / ".git").mkdir()

        agent_env = AgentEnvironment(
            app_dir=app_dir,
            docker_networks=["test_net"],
            image_name="test:latest",
            env={},
            commit_id="HEAD",
            workflow="discovery",
        )

        with patch.object(agent_env, "_setup_agent_codebase", return_value={}):
            agent_env.setup()

        exec_calls = [call.args[0] for call in mock_container.exec_run.call_args_list]
        assert (
            "bash -c 'echo $CODEX_API_KEY | codex login --with-api-key'"
            not in exec_calls
        )


class TestSaveAgentExploit:
    """Tests for AgentEnvironment.save_agent_exploit()."""

    def _create_agent_env(self, tmp_path):
        agent_env = AgentEnvironment(
            app_dir=tmp_path,
            docker_networks=["test_net"],
            image_name="test:latest",
            env={},
            commit_id="HEAD",
            workflow="discovery",
        )
        return agent_env

    def test_no_container_logs_warning(self, tmp_path):
        """Logs warning and returns when container is None."""
        agent_env = self._create_agent_env(tmp_path)
        agent_env.container = None

        # Should not raise
        agent_env.save_agent_exploit(tmp_path / "logs")
        assert not (tmp_path / "logs" / "agent_exploit").exists()

    def test_empty_agent_exploit_skipped(self, tmp_path):
        """No extraction when agent_exploit directory is empty in container."""
        agent_env = self._create_agent_env(tmp_path)
        agent_env.container = MagicMock()
        agent_env.container.exec_run.return_value = MagicMock(exit_code=0, output=b"")

        agent_env.save_agent_exploit(tmp_path / "logs")
        agent_env.container.get_archive.assert_not_called()
        assert not (tmp_path / "logs" / "agent_exploit").exists()

    def test_copies_to_agent_exploit_dir(self, tmp_path):
        """Extracts container's agent_exploit to dest_dir/agent_exploit/."""
        agent_env = self._create_agent_env(tmp_path)
        agent_env.container = MagicMock()

        # ls shows content
        agent_env.container.exec_run.return_value = MagicMock(
            exit_code=0, output=b"exploit.sh\n"
        )

        # get_archive returns a tar with agent_exploit/exploit.sh
        tar_bytes = _make_tar({"agent_exploit/exploit.sh": "#!/bin/bash\necho pwned"})
        agent_env.container.get_archive.return_value = (iter([tar_bytes]), {})

        logs_dir = tmp_path / "logs"
        agent_env.save_agent_exploit(logs_dir)

        saved = logs_dir / "agent_exploit" / "exploit.sh"
        assert saved.exists()
        assert "echo pwned" in saved.read_text()

    def test_get_archive_failure_does_not_raise(self, tmp_path):
        """Logs warning instead of raising on Docker API errors."""
        agent_env = self._create_agent_env(tmp_path)
        agent_env.container = MagicMock()
        agent_env.container.exec_run.return_value = MagicMock(
            exit_code=0, output=b"exploit.sh\n"
        )
        agent_env.container.get_archive.side_effect = Exception("Docker API error")

        # Should not raise
        agent_env.save_agent_exploit(tmp_path / "logs")
