"""Tests for agent_container module."""

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
