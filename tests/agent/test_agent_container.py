"""Tests for agent_container module."""

import io
import os
import subprocess
import tarfile
from unittest.mock import MagicMock, patch

import docker.errors

from agent.runtime.container import AgentEnvironment
from evaluation.task_bundle import SyntheticBundle, ZerodayBundle

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
}


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
            workflow="exploit",
        )

        assert agent_env.vuln_id is None


class TestAgentEnvironmentPostCheckoutHook:
    """Tests for post_checkout_hook staging behavior."""

    @staticmethod
    def _git(cwd, *args):
        subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, **_GIT_ENV},
        )

    @patch("agent.runtime.container.docker.from_env")
    def test_post_checkout_hook_applies_to_staged_copy_only(
        self, mock_from_env, tmp_path
    ):
        mock_from_env.return_value = MagicMock()

        app_dir = tmp_path / "app"
        codebase_dir = app_dir / "codebase"
        codebase_dir.mkdir(parents=True)

        server_file = codebase_dir / "server.py"
        server_file.write_text(
            "def handle_request(user):\n"
            "    if not user.is_authenticated:\n"
            "        raise PermissionError('Not authenticated')\n"
            "    return process(user)\n"
        )
        self._git(codebase_dir, "init", "-q")
        self._git(codebase_dir, "add", "-A")
        self._git(codebase_dir, "commit", "-m", "initial", "-q")

        patch_path = (
            app_dir / "synthetic_vulnerabilities" / "vuln_0" / "vulnerability.patch"
        )
        patch_path.parent.mkdir(parents=True)
        patch_path.write_text(
            "diff --git a/server.py b/server.py\n"
            "--- a/server.py\n"
            "+++ b/server.py\n"
            "@@ -1,4 +1,2 @@\n"
            " def handle_request(user):\n"
            "-    if not user.is_authenticated:\n"
            "-        raise PermissionError('Not authenticated')\n"
            "     return process(user)\n"
        )

        commit_id = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=codebase_dir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        def post_checkout_hook(repo_dir):
            subprocess.run(
                ["git", "apply", str(patch_path)],
                cwd=repo_dir,
                check=True,
                capture_output=True,
                text=True,
            )

        agent_env = AgentEnvironment(
            app_dir=app_dir,
            docker_networks=["test_net"],
            image_name="test:latest",
            env={},
            commit_id=commit_id,
            workflow="redteam",
            include_git_history=True,
            post_checkout_hook=post_checkout_hook,
        )

        agent_env._setup_agent_codebase()

        agent_server = app_dir / "agent_codebase" / "server.py"
        assert "is_authenticated" not in agent_server.read_text()
        assert "is_authenticated" in server_file.read_text()

    @patch("agent.runtime.container.docker.from_env")
    def test_synthetic_bundle_phase1_snapshot_is_vulnerable(
        self, mock_from_env, tmp_path
    ):
        mock_from_env.return_value = MagicMock()

        app_dir = tmp_path / "apps" / "app"
        codebase_dir = app_dir / "codebase"
        codebase_dir.mkdir(parents=True)

        server_file = codebase_dir / "server.py"
        server_file.write_text(
            "def handle_request(user):\n"
            "    if not user.is_authenticated:\n"
            "        raise PermissionError('Not authenticated')\n"
            "    return process(user)\n"
        )
        self._git(codebase_dir, "init", "-q")
        self._git(codebase_dir, "add", "-A")
        self._git(codebase_dir, "commit", "-m", "initial", "-q")

        patch_path = (
            app_dir / "synthetic_vulnerabilities" / "vuln_0" / "vulnerability.patch"
        )
        patch_path.parent.mkdir(parents=True)
        patch_path.write_text(
            "diff --git a/server.py b/server.py\n"
            "--- a/server.py\n"
            "+++ b/server.py\n"
            "@@ -1,4 +1,2 @@\n"
            " def handle_request(user):\n"
            "-    if not user.is_authenticated:\n"
            "-        raise PermissionError('Not authenticated')\n"
            "     return process(user)\n"
        )

        commit_id = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=codebase_dir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        bundle = SyntheticBundle(app_dir=app_dir, vuln_id="vuln_0")
        agent_env = AgentEnvironment(
            app_dir=app_dir,
            docker_networks=["test_net"],
            image_name="test:latest",
            env={},
            commit_id=commit_id,
            workflow="redteam",
            include_git_history=True,
            post_checkout_hook=bundle.prepare_phase1_codebase,
        )

        agent_env._setup_agent_codebase()

        agent_server = app_dir / "agent_codebase" / "server.py"
        assert "is_authenticated" not in agent_server.read_text()
        assert "is_authenticated" in server_file.read_text()

    @patch("agent.runtime.container.docker.from_env")
    def test_zeroday_bundle_phase1_snapshot_stays_baseline(
        self, mock_from_env, tmp_path
    ):
        mock_from_env.return_value = MagicMock()

        project_root = tmp_path
        app_dir = project_root / "apps" / "app"
        codebase_dir = app_dir / "codebase"
        codebase_dir.mkdir(parents=True)

        server_file = codebase_dir / "server.py"
        server_file.write_text(
            "def handle_request(user):\n" "    return process(user)\n"
        )
        self._git(codebase_dir, "init", "-q")
        self._git(codebase_dir, "add", "-A")
        self._git(codebase_dir, "commit", "-m", "initial", "-q")

        task_dir = project_root / "zerodays" / "reports" / "app" / "report-1" / "task"
        task_dir.mkdir(parents=True)
        (task_dir / "fix.patch").write_text("diff --git a/server.py b/server.py\n")

        # Dirty host tree. git_checkout inside _setup_agent_codebase should
        # restore the baseline before the snapshot is taken.
        server_file.write_text("CORRUPTED\n")

        commit_id = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=codebase_dir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        bundle = ZerodayBundle(
            project_root=project_root,
            app_name="app",
            task="report-1",
        )
        agent_env = AgentEnvironment(
            app_dir=app_dir,
            docker_networks=["test_net"],
            image_name="test:latest",
            env={},
            commit_id=commit_id,
            workflow="redteam",
            include_git_history=True,
            post_checkout_hook=bundle.prepare_phase1_codebase,
        )

        agent_env._setup_agent_codebase()

        agent_server = app_dir / "agent_codebase" / "server.py"
        assert (
            agent_server.read_text()
            == "def handle_request(user):\n    return process(user)\n"
        )
        assert (
            server_file.read_text()
            == "def handle_request(user):\n    return process(user)\n"
        )


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


class TestAgentNetworkIsolation:
    """Verify agent container is not handed pivot primitives at start."""

    @patch("agent.runtime.container.docker.from_env")
    def test_agent_container_has_no_host_gateway(self, mock_from_env, tmp_path):
        """Agent must not receive host.docker.internal:host-gateway mapping.

        With the mapping in place the agent could reach any host-bound service
        (V4 in documentation/proposals/agent_isolation/). The adb-proxy sidecar
        keeps the mapping intentionally; this test guards the agent only.
        """
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
            workflow="exploit",
        )

        with patch.object(agent_env, "_setup_agent_codebase", return_value={}):
            agent_env.setup()

        run_kwargs = mock_client.containers.run.call_args.kwargs
        assert "extra_hosts" not in run_kwargs, (
            "Agent container received extra_hosts kwarg — V4 host-pivot risk. "
            f"Got: {run_kwargs.get('extra_hosts')}"
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
            workflow="exploit",
        )
        return agent_env

    def test_no_container_logs_warning(self, tmp_path):
        """Logs warning and returns when container is None."""
        agent_env = self._create_agent_env(tmp_path)
        agent_env.container = None

        # Should not raise
        agent_env.save_agent_exploit(tmp_path / "logs")
        assert not (tmp_path / "logs" / "agent_exploit").exists()

    def test_missing_agent_exploit_skipped(self, tmp_path):
        """No extraction when agent_exploit does not exist in container.

        get_archive raises NotFound on missing paths; _save_container_dir
        downgrades to INFO and writes nothing. Important because SIGKILL'd
        containers can't satisfy a pre-existence check via `exec_run`."""
        agent_env = self._create_agent_env(tmp_path)
        agent_env.container = MagicMock()
        agent_env.container.get_archive.side_effect = docker.errors.NotFound("no path")

        agent_env.save_agent_exploit(tmp_path / "logs")
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


class TestAuthEnvPassthrough:
    """Auth tokens set in the operator's env reach the agent container env_vars."""

    @patch("agent.runtime.container.docker.from_env")
    def test_set_auth_vars_forwarded_to_container(
        self, mock_from_env, tmp_path, monkeypatch
    ):
        """When the operator has OPENAI_API_KEY etc. in their env, those names
        appear in the container's env_vars dict."""
        from agent.runtime.container import setup_agent_environment

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oat-test")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        mock_client = MagicMock()
        mock_from_env.return_value = mock_client
        mock_client.images.get.return_value = MagicMock()
        mock_container = MagicMock()
        mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"")
        mock_client.containers.run.return_value = mock_container
        mock_client.containers.get.side_effect = docker.errors.NotFound("not found")

        app_dir = tmp_path / "app"
        (app_dir / "codebase" / ".git").mkdir(parents=True)

        with patch(
            "agent.runtime.container.AgentEnvironment._setup_agent_codebase",
            return_value={},
        ), patch("agent.runtime.container._start_adb_proxy"), patch(
            "agent.runtime.container._disable_emulator_root"
        ), patch(
            "agent.runtime.container.firewall.start"
        ), patch(
            "agent.runtime.container.firewall.proxy_url", return_value="http://proxy"
        ), patch(
            "agent.runtime.container.firewall.build_no_proxy", return_value=""
        ):
            setup_agent_environment(
                app_dir=app_dir,
                agent_image="test:latest",
                metadata={"package_name": "com.example", "commit_version": "HEAD"},
                network_mode="restricted",
                workflow="exploit",
            )

        env_vars = mock_client.containers.run.call_args.kwargs["environment"]
        assert env_vars.get("OPENAI_API_KEY") == "sk-test"
        assert env_vars.get("CLAUDE_CODE_OAUTH_TOKEN") == "oat-test"
        assert "ANTHROPIC_API_KEY" not in env_vars
