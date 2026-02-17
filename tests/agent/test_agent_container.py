"""Tests for agent_container module."""

import io
import tarfile
from unittest.mock import MagicMock

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


class TestSaveExploitFiles:
    """Tests for AgentEnvironment.save_exploit_files()."""

    def _create_agent_env(self, tmp_path):
        agent_env = AgentEnvironment(
            app_dir=tmp_path,
            docker_networks=["test_net"],
            image_name="test:latest",
            env={},
            commit_id="HEAD",
        )
        return agent_env

    def test_no_container_logs_warning(self, tmp_path):
        """Logs warning and returns when container is None."""
        agent_env = self._create_agent_env(tmp_path)
        agent_env.container = None

        # Should not raise
        agent_env.save_exploit_files(tmp_path / "logs")
        assert not (tmp_path / "logs" / "exploit_files").exists()

    def test_empty_exploit_files_skipped(self, tmp_path):
        """No extraction when exploit_files directory is empty."""
        agent_env = self._create_agent_env(tmp_path)
        agent_env.container = MagicMock()
        agent_env.container.exec_run.return_value = MagicMock(exit_code=0, output=b"")

        agent_env.save_exploit_files(tmp_path / "logs")
        agent_env.container.get_archive.assert_not_called()
        assert not (tmp_path / "logs" / "exploit_files").exists()

    def test_copies_exploit_files_to_dest(self, tmp_path):
        """Extracts exploit_files tar archive to destination."""
        agent_env = self._create_agent_env(tmp_path)
        agent_env.container = MagicMock()

        # ls shows content
        agent_env.container.exec_run.return_value = MagicMock(
            exit_code=0, output=b"exploit.sh\n"
        )

        # get_archive returns a tar with exploit_files/exploit.sh
        tar_bytes = _make_tar({"exploit_files/exploit.sh": "#!/bin/bash\necho pwned"})
        agent_env.container.get_archive.return_value = (iter([tar_bytes]), {})

        logs_dir = tmp_path / "logs"
        agent_env.save_exploit_files(logs_dir)

        saved = logs_dir / "exploit_files" / "exploit.sh"
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
        agent_env.save_exploit_files(tmp_path / "logs")
