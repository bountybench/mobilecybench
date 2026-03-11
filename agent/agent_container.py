import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Dict, List, Optional

import docker
import docker.errors

from agent.backend.docker_setup import AGENT_HOST_PORT
from utils.discovery_honeypot import inject_discovery_honeypot
from utils.git_utils import (
    cleanup_git_branches,
    git_checkout,
    git_setup_dev_branch,
    git_submodule_update,
    initialize_git_repository,
    onerror,
    prepare_git_directory,
)
from utils.logger import logger

# ---------------------------------------------------------------------------
# ADB proxy sidecar constants
# ---------------------------------------------------------------------------
ADB_PROXY_CONTAINER = "adb-proxy"
ADB_PROXY_IMAGE = "python:3.11-slim"
ADB_PROXY_PORT = 5037
APP_NET = "app_net"


class AgentEnvironment:
    def __init__(
        self,
        app_dir: Path,
        docker_networks: List[str],
        image_name: str,
        env: Dict[str, str],
        commit_id: str,
        mode: Optional[str] = None,
        workflow: str = "discovery",
        package_name: Optional[str] = None,
        vuln_id: Optional[str] = None,
        include_git_history: bool = True,
    ):
        self.app_dir = app_dir
        self.app_name = app_dir.name
        self.docker_networks = docker_networks
        self.image_name = image_name
        self.env = env
        self.commit_id = commit_id
        self.mode = mode
        self.workflow = workflow
        self.package_name = package_name
        self.vuln_id = vuln_id
        self.include_git_history = include_git_history

        import traceback

        try:
            self.client = docker.from_env()
            logger.info("Docker client created successfully")
        except Exception as e:
            logger.error(f"Failed to create Docker client: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

        self.container = None

    def setup(self):
        """Set up the agent kali environment container."""
        container_name = "kali-container"

        # Remove existing container FIRST, before any setup work
        try:
            existing_container = self.client.containers.get(container_name)
            logger.info(f"Removing existing container: {container_name}")
            existing_container.remove(force=True)
        except docker.errors.NotFound:
            # no need to raise if container doesn't exist
            pass

        print(f"Checking for image {self.image_name}...")
        logger.info(f"Ensuring image {self.image_name} is available...")

        # First check if image exists locally
        try:
            self.client.images.get(self.image_name)
            print(f"Image {self.image_name} found locally")
            logger.info(f"Image {self.image_name} found locally, skipping pull")
        except docker.errors.ImageNotFound:
            # Image not found locally, try to pull it
            logger.info(
                f"Image {self.image_name} not found locally, pulling from registry..."
            )
            try:
                seen_statuses = set()
                pulling_started = False

                for line in self.client.api.pull(
                    self.image_name, stream=True, decode=True
                ):
                    if "status" in line:
                        status = line["status"]
                        layer_id = line.get("id", "")

                        if status == "Pulling fs layer" and not pulling_started:
                            print(
                                "Image not cached locally, pulling from registry (this may take several minutes for large images)..."
                            )
                            pulling_started = True

                        # only show meaningful status changes to avoid bloating output
                        if status in [
                            "Pulling fs layer",
                            "Download complete",
                            "Pull complete",
                            "Already exists",
                        ]:
                            status_key = f"{layer_id}:{status}"
                            if status_key not in seen_statuses:
                                if layer_id:
                                    print(f"  {layer_id}: {status}")
                                else:
                                    print(f"  {status}")
                                seen_statuses.add(status_key)

                print(f"Image {self.image_name} ready")
                logger.info(f"Image {self.image_name} ready")
            except docker.errors.APIError as e:
                logger.error(f"Failed to pull image {self.image_name}: {e}")
                raise
            except Exception as e:
                logger.error(f"Unexpected error pulling image: {e}")
                raise

        # Don't pass internal credential blobs as container env vars
        environment = {k: v for k, v in self.env.items() if not k.startswith("_")}
        extra_hosts = {"host.docker.internal": "host-gateway"}
        command = '/bin/bash -c "while true; do sleep 30; done"'
        network = self.docker_networks[0] if self.docker_networks else None

        # Mount self-signed root CA so requests to HTTPS apps' servers will work
        ca_volumes = self._setup_root_ca()

        # Setup agent codebase and get volume mapping
        volumes = None
        try:
            volumes = self._setup_agent_codebase()
            if ca_volumes:
                volumes.update(ca_volumes)

            # Setup verify_files and agent_output for synthetic vulnerability mode
            if self.vuln_id:
                verify_volumes = self._setup_verify_files()
                if verify_volumes:
                    volumes.update(verify_volumes)

                agent_output_volumes = self._setup_agent_output()
                if agent_output_volumes:
                    volumes.update(agent_output_volumes)

            self.container = self.client.containers.run(
                image=self.image_name,
                name=container_name,
                command=command,
                environment=environment,
                extra_hosts=extra_hosts,
                network=network,
                volumes=volumes,
                ports={f"{AGENT_HOST_PORT}/tcp": AGENT_HOST_PORT},
                stdin_open=True,
                tty=True,
                detach=True,
            )

            # Connect to additional networks if any
            for additional_network in self.docker_networks[1:]:
                network_obj = self.client.networks.get(additional_network)
                network_obj.connect(self.container)

            # Create agent_exploit and agent_output directories
            logger.info(
                "Creating agent_exploit and agent_output directories in container"
            )
            self.container.exec_run("mkdir -p /app/agent_exploit /app/agent_output")

            # Install self-signed CA into system trust store
            if ca_volumes:
                result = self.container.exec_run("update-ca-certificates")
                if result.exit_code == 0:
                    logger.info("Root CA installed in container trust store")
                else:
                    logger.warning(
                        f"Failed to install root CA: {result.output.decode()}"
                    )

            if self.mode == "codex":
                logger.info("Logging in to Codex CLI with API key...")
                result = self.container.exec_run(
                    "bash -c 'echo $CODEX_API_KEY | codex login --with-api-key'"
                )
                if result.exit_code == 0:
                    logger.info("Codex CLI logged in successfully")
                else:
                    logger.error(f"Codex login failed: {result.output.decode()}")
            elif self.mode == "claude-code":
                self.container.exec_run("mkdir -p /root/.claude")

                # Write credentials file inside the container
                creds_json = self.env.get("_CLAUDE_CODE_CREDENTIALS_JSON", "")
                if creds_json:
                    self.container.exec_run(
                        [
                            "bash",
                            "-c",
                            f"cat > /root/.claude/.credentials.json << 'CREDS_EOF'\n{creds_json}\nCREDS_EOF",
                        ]
                    )
                    logger.info("Wrote Claude Code credentials to container")

                # Pre-allow all tools so the CLI doesn't prompt for
                # permissions (--dangerously-skip-permissions refuses to
                # run as root).  Claude Code has no "allow all" wildcard,
                # so we list each tool.  Update this list if new tools
                # are added in future Claude Code releases.
                settings = json.dumps(
                    {
                        "permissions": {
                            "allow": [
                                "Bash",
                                "Read",
                                "Edit",
                                "Write",
                                "Grep",
                                "Glob",
                                "WebFetch",
                                "WebSearch",
                                "Agent",
                                "NotebookEdit",
                                "ToolSearch",
                                "Task",
                                "TaskOutput",
                                "TaskStop",
                                "TodoWrite",
                                "AskUserQuestion",
                                "Skill",
                                "EnterPlanMode",
                                "ExitPlanMode",
                                "EnterWorktree",
                            ]
                        }
                    }
                )
                self.container.exec_run(
                    [
                        "bash",
                        "-c",
                        f"cat > /root/.claude/settings.json << 'SETTINGS_EOF'\n{settings}\nSETTINGS_EOF",
                    ]
                )
                logger.info("Wrote Claude Code settings (all tools allowed)")

                # Verify authentication
                result = self.container.exec_run("bash -c 'claude auth status'")
                if result.exit_code == 0:
                    logger.info(
                        f"Claude Code authenticated: {result.output.decode().strip()}"
                    )
                else:
                    logger.warning(
                        f"Claude Code auth check failed: {result.output.decode()}"
                    )

        except Exception as e:
            logger.error(f"Setup failed: {e}")
            # Remove container if it was created
            if self.container:
                try:
                    self.container.remove(force=True)
                    self.container = None
                except Exception:
                    pass
            raise

    def _setup_agent_codebase(self):
        """Create a copy of codebase for the agent environment.

        If include_git_history is True: checkout specific commit, copy with full
        git history. If False: copy current state without git history and
        initialize a fresh repo.
        """
        original_codebase = self.app_dir / "codebase"
        agent_codebase = self.app_dir / "agent_codebase"
        staging_dir = self.app_dir / "agent_codebase.staging"

        # Always clean up staging directory first to ensure fresh start
        if staging_dir.exists():
            logger.info(f"Removing existing staging directory at {staging_dir}")
            shutil.rmtree(staging_dir, onerror=onerror)

        # Check if original_codebase is empty, if so use git_submodule_update
        if not original_codebase.exists() or not any(original_codebase.iterdir()):
            logger.info("Original codebase is empty, initializing submodule")
            git_submodule_update(self.app_dir)

        # Create staging directory
        logger.info(f"Creating staging directory at {staging_dir}")
        staging_dir.mkdir(parents=True, exist_ok=True)

        if not self.include_git_history:
            # Copy codebase without git history so agent cannot see prior commits
            logger.info("Copying codebase without git history")
            self.copy_files(original_codebase, staging_dir, ignore_git=True)

            # Initialize fresh git repo so agent can still use git commands
            logger.info("Initializing fresh git repository in staging directory")
            initialize_git_repository(staging_dir)

            # Create initial commit with all files
            subprocess.run(
                ["git", "add", "-A"],
                cwd=staging_dir,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "Initial commit"],
                cwd=staging_dir,
                check=True,
                capture_output=True,
            )
            # Create dev branch from this commit
            subprocess.run(
                ["git", "checkout", "-b", "dev"],
                cwd=staging_dir,
                check=True,
                capture_output=True,
            )
            logger.info("Created fresh git repo with 'main' and 'dev' branches")
        else:
            # Checkout specific commit and preserve full git history
            # Find the repository root (which contains .git)
            repo_root = original_codebase
            while repo_root.parent != repo_root:
                if (repo_root / ".git").exists():
                    break
                repo_root = repo_root.parent

            # Remove git index lock files (cross-platform)
            logger.info("Removing git index lock files")
            git_dir = Path(repo_root) / ".git"
            if git_dir.exists():
                # Use Python's pathlib to find and remove index.lock files
                for lock_file in git_dir.rglob("index.lock"):
                    try:
                        lock_file.unlink()
                        logger.debug(f"Removed lock file: {lock_file}")
                    except Exception as e:
                        logger.warning(f"Failed to remove lock file {lock_file}: {e}")

            # Checkout to commit_id in original_codebase
            logger.info(f"Checking out commit {self.commit_id} in {original_codebase}")
            git_checkout(original_codebase, self.commit_id, force=True)

            # Copy original_codebase to staging directory with git history
            logger.info(f"Copying {original_codebase} to {staging_dir}")
            self.copy_files(original_codebase, staging_dir, ignore_git=False)

            # Run git_setup_dev_branch in staging directory
            logger.info("Setting up dev branch in staging directory")
            git_setup_dev_branch(staging_dir)

            if self.workflow == "discovery" and self.package_name:
                logger.info(
                    "Injecting discovery honeypot into staged agent codebase for %s",
                    self.package_name,
                )
                inject_discovery_honeypot(staging_dir, self.package_name)

                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=staging_dir,
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    ["git", "commit", "-m", "Prepare environment"],
                    cwd=staging_dir,
                    check=True,
                    capture_output=True,
                )

        # Clean up any existing agent_codebase directory
        if agent_codebase.exists():
            logger.info(f"Removing existing agent_codebase at {agent_codebase}")
            shutil.rmtree(agent_codebase, onerror=onerror)

        # Move staging directory to agent_codebase
        logger.info(f"Moving staging directory to {agent_codebase}")
        shutil.move(str(staging_dir), str(agent_codebase))
        logger.info("✓ Agent codebase ready for mounting")

        # Return volume mapping for bind mount
        return {str(agent_codebase): {"bind": "/app/codebase", "mode": "ro"}}

    def _setup_verify_files(self):
        """Mount verify_files for the synthetic vulnerability."""
        verify_files_src = (
            self.app_dir / "synthetic_vulnerabilities" / self.vuln_id / "verify_files"
        )
        if not verify_files_src.is_dir():
            logger.warning(f"No verify_files directory found at {verify_files_src}")
            return None

        logger.info(f"Mounting verify_files at /app/verify_files/{self.vuln_id}")
        return {
            str(verify_files_src): {
                "bind": f"/app/verify_files/{self.vuln_id}",
                "mode": "ro",
            }
        }

    def _setup_agent_output(self):
        """Create and mount agent_output/ for the synthetic vulnerability.

        Volume-mounted so verify scripts on the host can read exploit results
        after the agent writes them inside the container.
        """
        agent_output_dir = (
            self.app_dir / "synthetic_vulnerabilities" / self.vuln_id / "agent_output"
        )
        # Clean stale data from previous runs, then create fresh
        if agent_output_dir.exists():
            shutil.rmtree(agent_output_dir)
        agent_output_dir.mkdir(parents=True)

        logger.info("Mounting agent_output at /app/agent_output")
        return {
            str(agent_output_dir): {
                "bind": "/app/agent_output",
                "mode": "rw",
            }
        }

    def _setup_root_ca(self) -> Optional[dict]:
        """Mount the project's self-signed root CA into the container.

        Returns volume dict mapping rootCA.pem into the system CA directory,
        or None if the CA file doesn't exist.
        """
        project_root = self.app_dir.parent.parent
        root_ca = project_root / "tls" / "rootCA.pem"
        if not root_ca.exists():
            logger.info("No tls/rootCA.pem found, skipping CA mount")
            return None

        ca_bundle = "/etc/ssl/certs/ca-certificates.crt"
        self.env["REQUESTS_CA_BUNDLE"] = ca_bundle
        self.env["SSL_CERT_FILE"] = ca_bundle
        self.env["NODE_EXTRA_CA_CERTS"] = "/usr/local/share/ca-certificates/rootCA.crt"

        logger.info("Mounting rootCA.pem into container trust store")
        return {
            str(root_ca): {
                "bind": "/usr/local/share/ca-certificates/rootCA.crt",
                "mode": "ro",
            }
        }

    def copy_files(
        self,
        source: Path,
        destination: Path,
        ignore_git: bool = True,
        copy_dir: bool = False,
        skip_hidden_files: bool = False,
    ):
        """Copy files and directories from source to destination.

        Args:
            source: Source path to copy from
            destination: Destination path to copy to
            ignore_git: Whether to ignore .git files and directories
            copy_dir: Whether to copy source_dir's name
            skip_hidden_files: Whether to skip all .hidden_files from copy
        """
        source = source.resolve()
        destination = destination.resolve()

        try:
            if source.is_file():
                shutil.copy2(source, destination)
                logger.debug(f"Copied file {source} to {destination}")
                return

            if not source.is_dir():
                raise ValueError(f"Source {source} is neither a file nor a directory")

            if copy_dir:
                destination = destination / source.name
                logger.debug(f"copying full directory, new dest path: {destination}")

            def ignore_func(directory, contents):
                ignored = []

                # For Git files - only if not already handled by skip_hidden_files
                if ignore_git and not skip_hidden_files:
                    ignored.extend(
                        [
                            item
                            for item in contents
                            if item == ".git" or item.startswith(".git/")
                        ]
                    )

                # For all dot files
                if skip_hidden_files:
                    ignored.extend([item for item in contents if item.startswith(".")])

                return ignored

            # Copy the directory structure
            shutil.copytree(
                source,
                destination,
                dirs_exist_ok=True,
                ignore=ignore_func,
                symlinks=True,
            )

            # Handle Git repository if needed
            git_file = source / ".git"
            if not ignore_git and git_file.exists():
                if git_file.is_file():
                    self._handle_git_submodule(git_file, source, destination)
                elif git_file.is_dir():
                    self._handle_git_directory(git_file, destination)

            logger.debug(f"Copied directory {source} to {destination}")
        except Exception as e:
            logger.error(f"An error occurred while copying files: {e}")
            raise

    def _handle_git_submodule(self, git_file, source, destination):
        """Handle Git submodule reference files."""
        # Read the submodule reference
        with open(git_file, "r") as f:
            content = f.read().strip()

        if not content.startswith("gitdir:"):
            # It's a regular .git file, just copy it
            shutil.copy2(git_file, destination / ".git")
            logger.debug(f"Copied .git file from {git_file} to {destination / '.git'}")
            return

        # Extract the actual Git directory path
        gitdir_path = content.split("gitdir:")[1].strip()
        if not os.path.isabs(gitdir_path):
            gitdir_path = os.path.normpath(os.path.join(source, gitdir_path))

        actual_git_dir = Path(gitdir_path)
        if not (actual_git_dir.exists() and actual_git_dir.is_dir()):
            logger.warning(
                f"Referenced Git directory {actual_git_dir} does not exist or is not a directory"
            )
            # Fall back to copying the reference file
            shutil.copy2(git_file, destination / ".git")
            return

        # Setup the destination Git repository
        dest_git_path = destination / ".git"
        prepare_git_directory(dest_git_path)

        try:
            initialize_git_repository(destination)
            self._copy_git_directories(actual_git_dir, dest_git_path)
            self._copy_git_files(actual_git_dir, dest_git_path)
            self._create_clean_git_config(dest_git_path)
            logger.debug(f"Copied Git data from {actual_git_dir} to {dest_git_path}")

            # Clean up branches and make detached HEAD the new main branch
            cleanup_git_branches(destination)
            logger.debug(f"Cleaned up Git branches in {destination}")
        except Exception as e:
            logger.error(f"Failed to initialize Git repository: {e}")
            raise

    def _handle_git_directory(self, git_dir, destination):
        """Handle regular Git directories."""
        dest_git_path = destination / ".git"
        prepare_git_directory(dest_git_path)

        try:
            initialize_git_repository(destination)
            self._copy_git_directories(git_dir, dest_git_path)
            self._copy_git_files(git_dir, dest_git_path)
            self._create_clean_git_config(dest_git_path)
            logger.debug(f"Copied Git data from {git_dir} to {dest_git_path}")

            # Clean up branches and make detached HEAD the new main branch
            cleanup_git_branches(destination)
            logger.debug(f"Cleaned up Git branches in {destination}")
        except Exception as e:
            logger.error(f"Failed to initialize Git repository: {e}")
            raise

    def _copy_git_directories(self, src_git_dir, dest_git_path):
        """Copy Git directories like objects, refs, hooks, and info."""
        for dir_name in ["objects", "refs", "hooks", "info"]:
            src_dir = src_git_dir / dir_name
            dst_dir = dest_git_path / dir_name
            if src_dir.exists():
                if not dst_dir.exists():
                    dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)

    def _copy_git_files(self, src_git_dir, dest_git_path):
        """Copy important Git files like HEAD, description, and index."""
        for file_name in ["HEAD", "description", "index"]:
            src_file = src_git_dir / file_name
            if src_file.exists():
                shutil.copy2(src_file, dest_git_path / file_name)

    def _create_clean_git_config(self, dest_git_path):
        """Create a clean Git config file without worktree references."""
        with open(dest_git_path / "config", "w") as f:
            f.write(
                "[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n"
            )

    def delete_agent_codebase(self):
        agent_codebase = self.app_dir / "agent_codebase"

        if not agent_codebase.exists():
            logger.info("agent_codebase does not exist, nothing to reset")
            return

        try:
            # Simple approach: delete the entire directory
            logger.info(f"Deleting agent_codebase directory at {agent_codebase}")
            shutil.rmtree(agent_codebase, onerror=onerror)
            logger.info("Successfully deleted agent_codebase directory")

        except Exception as e:
            logger.error(f"Failed to reset agent_codebase: {e}")
            raise

    def _save_container_dir(self, container_path: str, dest_dir: Path) -> None:
        """Copy a directory from the container to dest_dir.

        Must be called before cleanup() destroys the container.
        """
        dir_name = container_path.rstrip("/").split("/")[-1]
        if not self.container:
            logger.warning(f"No container available, cannot save {dir_name}")
            return

        try:
            result = self.container.exec_run(f"ls {container_path}")
            if result.exit_code != 0 or not result.output.strip():
                logger.info(f"No {dir_name} found in container")
                return

            bits, _ = self.container.get_archive(container_path)
            stream = io.BytesIO()
            for chunk in bits:
                stream.write(chunk)
            stream.seek(0)

            dest_dir.mkdir(parents=True, exist_ok=True)
            with tarfile.open(fileobj=stream) as tar:
                tar.extractall(path=dest_dir, filter="data")

            logger.info(f"Saved {dir_name} to {dest_dir / dir_name}")
        except Exception as e:
            logger.warning(f"Failed to save {dir_name}: {e}")

    def save_agent_exploit(self, dest_dir: Path) -> None:
        """Copy /app/agent_exploit/ from the container to dest_dir/agent_exploit/."""
        self._save_container_dir("/app/agent_exploit", dest_dir)

    def save_agent_output(self, dest_dir: Path) -> None:
        """Copy /app/agent_output/ from the container to dest_dir/agent_output/."""
        self._save_container_dir("/app/agent_output", dest_dir)

    def cleanup(self):
        """Clean up the agent environment (stop and remove container)."""
        if self.container:
            try:
                logger.info(f"Stopping container: {self.container.name}")
                self.container.stop(timeout=10)
                self.container.remove(force=True)
                logger.info("Container stopped and removed")
            except Exception as e:
                logger.warning(f"Error cleaning up container: {e}")
        self.container = None
        _stop_adb_proxy()


def create_docker_network(network_name: str = "shared_net") -> None:
    """Create Docker networks if they don't exist."""
    client = docker.from_env()

    try:
        client.networks.get(network_name)
        logger.info(f"Docker network '{network_name}' already exists")
    except docker.errors.NotFound:
        client.networks.create(network_name, driver="bridge")
        logger.info(f"Created Docker network '{network_name}'")

    # Also create the internal app_net for agent isolation.
    # app_net is --internal so containers on it alone cannot reach the host
    # or internet.  The kali container is on both app_net (for ADB proxy and
    # app servers) and shared_net (for internet/API access).
    try:
        client.networks.get(APP_NET)
        logger.info(f"Docker network '{APP_NET}' already exists")
    except docker.errors.NotFound:
        client.networks.create(APP_NET, driver="bridge", internal=True)
        logger.info(f"Created internal Docker network '{APP_NET}'")


def _start_adb_proxy() -> None:
    """Start the ADB filtering proxy sidecar container.

    The proxy sits on both ``shared_net`` (to reach the host ADB server)
    and ``app_net`` (so the kali container can reach it).  It filters
    ADB protocol messages, blocking ``root:``, ``unroot:``, and ``shell:su``.
    """
    client = docker.from_env()

    # Remove any stale proxy container
    _stop_adb_proxy()

    proxy_script = (
        Path(__file__).resolve().parent.parent / "utils" / "adb_filter_proxy.py"
    )
    if not proxy_script.exists():
        raise FileNotFoundError(f"ADB filter proxy script not found: {proxy_script}")

    logger.info("Starting ADB proxy sidecar...")
    proxy_container = client.containers.run(
        image=ADB_PROXY_IMAGE,
        name=ADB_PROXY_CONTAINER,
        command="python3 /opt/adb_filter_proxy.py",
        detach=True,
        network="shared_net",
        extra_hosts={"host.docker.internal": "host-gateway"},
    )

    # Also connect to app_net so kali can reach the proxy
    app_net = client.networks.get(APP_NET)
    app_net.connect(proxy_container)

    # Copy the filter script and shared patterns into the container
    import tarfile as _tarfile

    patterns_module = proxy_script.parent / "adb_blocked_patterns.py"

    buf = io.BytesIO()
    with _tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(str(proxy_script), arcname="adb_filter_proxy.py")
        tar.add(str(patterns_module), arcname="adb_blocked_patterns.py")
    buf.seek(0)
    proxy_container.put_archive("/opt", buf)

    # Restart so it picks up the script (command was set at creation)
    proxy_container.restart()

    logger.info(
        f"ADB proxy sidecar started "
        f"(:{ADB_PROXY_PORT} -> host.docker.internal:{ADB_PROXY_PORT})"
    )


def _stop_adb_proxy() -> None:
    """Stop and remove the ADB proxy sidecar container if it exists."""
    client = docker.from_env()
    try:
        container = client.containers.get(ADB_PROXY_CONTAINER)
        container.stop(timeout=5)
        container.remove(force=True)
        logger.info("ADB proxy sidecar stopped and removed")
    except docker.errors.NotFound:
        pass
    except Exception as e:
        logger.warning(f"Error stopping ADB proxy: {e}")


def _disable_emulator_root() -> None:
    """Disable root access on the emulator.

    Two layers of defense:
    1. ``adb unroot`` — restarts adbd as non-root.
    2. Bind-mount an empty, mode-000 file over ``/system/xbin/su`` so the
       ``su`` binary cannot be executed even if the agent bypasses the proxy
       (e.g. by pushing a script that calls su at runtime).

    This must run *before* ``adb unroot`` drops our ability to do root ops.
    """
    try:
        # Ensure we have root for the setup steps
        subprocess.run(["adb", "root"], capture_output=True, timeout=10)
        subprocess.run(["adb", "wait-for-device"], capture_output=True, timeout=30)

        # Disable su binary via bind mount
        subprocess.run(
            [
                "adb",
                "shell",
                "touch /data/local/tmp/.fake_su"
                " && chmod 000 /data/local/tmp/.fake_su"
                " && mount --bind /data/local/tmp/.fake_su /system/xbin/su",
            ],
            capture_output=True,
            timeout=10,
        )

        # Drop root
        subprocess.run(["adb", "unroot"], capture_output=True, timeout=10)
    except Exception as e:
        logger.warning(f"Failed to fully disable emulator root: {e}")
        # Still try to unroot even if bind mount failed
        try:
            subprocess.run(["adb", "unroot"], capture_output=True, timeout=10)
        except Exception:
            pass


def _connect_app_servers_to_app_net(container_names: list) -> None:
    """Connect app server containers to the internal app_net.

    App servers are started on ``shared_net`` by their docker-compose files.
    We also connect them to ``app_net`` so the kali container can reach them.
    """
    client = docker.from_env()
    try:
        app_net = client.networks.get(APP_NET)
    except docker.errors.NotFound:
        logger.warning(f"Network {APP_NET} not found, skipping app server connection")
        return

    for name in container_names:
        try:
            container = client.containers.get(name)
            app_net.connect(container)
            logger.info(f"Connected app server '{name}' to {APP_NET}")
        except docker.errors.APIError as e:
            if "already exists" in str(e):
                logger.info(f"App server '{name}' already on {APP_NET}")
            else:
                logger.warning(f"Failed to connect '{name}' to {APP_NET}: {e}")
        except docker.errors.NotFound:
            logger.warning(f"App server container '{name}' not found")


def _load_claude_code_credentials() -> Optional[str]:
    """Load Claude Code OAuth credentials from environment variables.

    Expects ``CLAUDE_CODE_OAUTH_TOKEN`` (required) and optionally
    ``CLAUDE_CODE_OAUTH_REFRESH_TOKEN`` to be set in ``agent/.env``.
    See ``agent/.env.example`` for details.

    Returns the raw JSON string to write into
    ``~/.claude/.credentials.json`` inside the container, or *None* if
    no credentials were found.
    """
    # Ensure agent/.env is loaded before reading credentials.
    # This function is called during setup_runtime_environment(), which
    # runs before setup_agent() where the agent's __init__ loads .env.
    from dotenv import load_dotenv

    agent_env_file = Path(__file__).parent / ".env"
    if agent_env_file.exists():
        load_dotenv(agent_env_file, override=True)

    token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
    refresh = os.environ.get("CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "")
    if token:
        creds = {
            "claudeAiOauth": {
                "accessToken": token,
                "refreshToken": refresh,
                "expiresAt": 0,
                "scopes": [
                    "user:inference",
                    "user:profile",
                    "user:sessions:claude_code",
                ],
            }
        }
        logger.info("Built Claude Code credentials from environment variables")
        return json.dumps(creds)

    logger.warning(
        "No Claude Code credentials found. " "Set CLAUDE_CODE_OAUTH_TOKEN in agent/.env"
    )
    return None


def setup_agent_environment(
    app_dir: Path,
    agent_image: str,
    metadata: dict,
    workflow: str = "discovery",  # "discovery", "detection", or "exploit"
    vuln_id: Optional[str] = None,
    agent_mode: str = "custom",
) -> AgentEnvironment:
    """
    Set up the agent environment container.

    Args:
        app_dir: Application directory
        agent_image: Docker image to use for agent
        metadata: App metadata dict
        workflow: Evaluation workflow type ("discovery", "detection", or "exploit")
        vuln_id: Vulnerability ID for exploit workflow
        agent_mode: Agent mode ("custom", "codex", or "claude-code")

    Returns:
        AgentEnvironment instance
    """
    # Create docker networks (shared_net + internal app_net)
    create_docker_network()

    # Start ADB filtering proxy sidecar (on shared_net + app_net)
    _start_adb_proxy()

    # Connect app server containers to app_net so kali can reach them
    container_names = metadata.get("container_names", [])
    _connect_app_servers_to_app_net(container_names)

    # Drop root on the emulator (setup phase already injected certs as root)
    _disable_emulator_root()
    logger.info("Emulator root privileges disabled")

    # Clear SSRF requests (only for discovery mode)
    if workflow == "discovery":
        try:
            from utils.ssrf_utils import clear_ssrf_requests

            logger.info("Clearing previous SSRF requests...")
            clear_ssrf_requests()
            logger.info("SSRF requests cleared")
        except Exception as e:
            logger.warning(f"Failed to clear SSRF requests: {e}")

    # ADB routes through the proxy sidecar on app_net (not directly to host)
    env_vars = {
        "ANDROID_ADB_SERVER_PORT": "5037",
        "ADB_SERVER_SOCKET": f"tcp:{ADB_PROXY_CONTAINER}:{ADB_PROXY_PORT}",
        "AGENT_SERVER_PORT": str(AGENT_HOST_PORT),
    }

    # Inject mode-specific environment variables
    if agent_mode == "codex":
        codex_key = os.environ.get("CODEX_API_KEY", "")
        if codex_key:
            env_vars["CODEX_API_KEY"] = codex_key
    elif agent_mode == "claude-code":
        # Load OAuth credentials for injection into the container.
        # Prefer the macOS Keychain (canonical source); fall back to env vars.
        claude_creds = _load_claude_code_credentials()
        if claude_creds:
            env_vars["_CLAUDE_CODE_CREDENTIALS_JSON"] = claude_creds

    # Get commit ID from metadata or use default
    commit_id = metadata.get("commit_id", "HEAD")

    agent_env = AgentEnvironment(
        app_dir=app_dir,
        docker_networks=[APP_NET, "shared_net"],
        image_name=agent_image,
        env=env_vars,
        commit_id=commit_id,
        mode=agent_mode,
        workflow=workflow,
        package_name=metadata.get("package_name"),
        vuln_id=vuln_id if workflow == "exploit" else None,
        include_git_history=(workflow != "exploit"),
    )

    agent_env.setup()

    return agent_env
