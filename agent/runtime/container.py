import io
import os
import shlex
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

import docker
import docker.errors

from agent import firewall
from agent.custom.backend.docker_setup import AGENT_HOST_PORT
from agent.firewall import AGENT_NET, EXTERNAL_BRIDGE, SHARED_NET
from agent.in_container.paths import EXPLOIT_DIR, OUTPUT_DIR, RUN_DIR
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

# Repo root: agent/runtime/container.py → parents[2] = <repo>. Used to
# resolve sibling trees (``utils/adb_filter_proxy.py``, ``agent/.env``).
_REPO_ROOT = Path(__file__).resolve().parents[2]

# ADB filter proxy sidecar. Joined to agent_net (the agent's only network);
# the proxy dual-homes onto the default bridge to reach the host's adb daemon.
ADB_PROXY_CONTAINER = "adb-proxy"
ADB_PROXY_IMAGE = "python:3.11-slim"
ADB_PROXY_PORT = 5037


class AgentEnvironment:
    def __init__(
        self,
        app_dir: Path,
        docker_networks: List[str],
        image_name: str,
        env: Dict[str, str],
        commit_id: Optional[str] = None,
        workflow: str = "exploit",
        package_name: Optional[str] = None,
        vuln_id: Optional[str] = None,
        include_git_history: bool = True,
        no_codebase: bool = False,
        post_checkout_hook: Optional[Callable[[Path], None]] = None,
        apk_path: Optional[Path] = None,
    ):
        self.app_dir = app_dir
        self.app_name = app_dir.name
        self.docker_networks = docker_networks
        self.image_name = image_name
        self.env = env
        self.commit_id = commit_id
        self.workflow = workflow
        self.package_name = package_name
        self.vuln_id = vuln_id
        self.include_git_history = include_git_history
        self.no_codebase = no_codebase
        # APK to stage for the agent when no_codebase=True. Kept separate from
        # vuln_id because vuln_id also gates verify_files mounting, which
        # redteam must never do.
        self.apk_path = apk_path
        # Optional callback invoked inside _setup_agent_codebase against the
        # staged copy before it is moved to agent_codebase/. Redteam+synthetic
        # uses this to apply vulnerability.patch so the agent sees the Phase 1
        # target source instead of the clean baseline without dirtying the
        # host app's working tree.
        self.post_checkout_hook = post_checkout_hook

        import traceback

        try:
            self.client = docker.from_env()
            logger.info("Docker client created successfully")
        except Exception as e:
            logger.error(f"Failed to create Docker client: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

        self.container = None
        # Populated by setup() from the live container handle right after
        # ``containers.run`` returns; survives cleanup so write_run_summary
        # can record it.
        self.image_digest: Optional[str] = None

    def setup(self):
        """Set up the agent kali environment container."""
        container_name = "kali-container"

        # Remove a stale kali-container left from a prior run before anything else.
        try:
            existing_container = self.client.containers.get(container_name)
            logger.info(f"Removing existing container: {container_name}")
            existing_container.remove(force=True)
        except docker.errors.NotFound:
            pass

        logger.info(f"Ensuring image {self.image_name} is available...")

        try:
            self.client.images.get(self.image_name)
            logger.info(f"Image {self.image_name} found locally, skipping pull")
        except docker.errors.ImageNotFound:
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
                            logger.info(
                                "Image not cached locally, pulling from registry "
                                "(this may take several minutes for large images)..."
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
                                    logger.info(f"  {layer_id}: {status}")
                                else:
                                    logger.info(f"  {status}")
                                seen_statuses.add(status_key)

                logger.info(f"Image {self.image_name} ready")
            except docker.errors.APIError as e:
                logger.error(f"Failed to pull image {self.image_name}: {e}")
                raise
            except Exception as e:
                logger.error(f"Unexpected error pulling image: {e}")
                raise

        # Don't pass internal credential blobs as container env vars
        environment = {k: v for k, v in self.env.items() if not k.startswith("_")}
        command = '/bin/bash -c "while true; do sleep 30; done"'
        network = self.docker_networks[0] if self.docker_networks else None

        # Mount self-signed root CA so requests to HTTPS apps' servers will work
        ca_volumes = self._setup_root_ca()

        # Setup agent resources: APK replaces codebase when no_codebase is set
        volumes = {}
        try:
            if self.no_codebase:
                apk_volumes = self._setup_agent_apk()
                if apk_volumes:
                    volumes.update(apk_volumes)
            else:
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
                network=network,
                volumes=volumes,
                ports={f"{AGENT_HOST_PORT}/tcp": AGENT_HOST_PORT},
                stdin_open=True,
                tty=True,
                detach=True,
            )
            # Snapshot the live image digest now — the container handle may
            # become unusable after cleanup, but ``write_run_summary`` runs
            # later in runner.py's outer finally and still needs this value.
            self.image_digest = self.container.image.id

            for additional_network in self.docker_networks[1:]:
                network_obj = self.client.networks.get(additional_network)
                network_obj.connect(self.container)

            # Create agent_exploit, agent_run, agent_output directories.
            # agent_run holds /app/agent_run/{result.json, conversation.jsonl, agent.log}
            # written by external (BYO-contract) agents; see harness.byo_agent.
            logger.info(
                "Creating agent_exploit, agent_run, agent_output directories in container"
            )
            self.container.exec_run(f"mkdir -p {EXPLOIT_DIR} {RUN_DIR} {OUTPUT_DIR}")

            # Persist environment variables into the container's shell
            # profile so that *every* shell session (including those
            # spawned by Claude Code's Bash tool) can see them.
            # Quote values: auth blobs (e.g. OPENCODE_AUTH_CONTENT JSON)
            # contain shell metacharacters that bare `export k=v` mangles.
            env_lines = "\n".join(
                f"export {k}={shlex.quote(str(v))}" for k, v in environment.items()
            )
            self.container.exec_run(
                ["bash", "-c", f"cat >> /root/.bashrc << 'ENVEOF'\n{env_lines}\nENVEOF"]
            )
            self.container.exec_run(
                [
                    "bash",
                    "-c",
                    f"mkdir -p /etc/profile.d && cat > /etc/profile.d/agent_env.sh << 'ENVEOF'\n{env_lines}\nENVEOF",
                ]
            )

            if ca_volumes:
                result = self.container.exec_run("update-ca-certificates")
                if result.exit_code == 0:
                    logger.info("Root CA installed in container trust store")
                else:
                    logger.warning(
                        f"Failed to install root CA: {result.output.decode()}"
                    )

        except Exception as e:
            logger.error(f"Setup failed: {e}")
            if self.container:
                try:
                    self.container.remove(force=True)
                    self.container = None
                except Exception as cleanup_err:
                    logger.warning(
                        f"Failed to remove agent container (kali-container): {cleanup_err}"
                    )
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

        # Always start from a clean staging dir; leftovers can poison the copy.
        if staging_dir.exists():
            logger.info(f"Removing existing staging directory at {staging_dir}")
            shutil.rmtree(staging_dir, onerror=onerror)

        if not original_codebase.exists() or not any(original_codebase.iterdir()):
            logger.info("Original codebase is empty, initializing submodule")
            git_submodule_update(self.app_dir)

        logger.info(f"Creating staging directory at {staging_dir}")
        staging_dir.mkdir(parents=True, exist_ok=True)

        if not self.include_git_history:
            # Strip history so the agent cannot see prior commits, then init a
            # fresh repo so it can still use git locally.
            logger.info("Copying codebase without git history")
            self.copy_files(original_codebase, staging_dir, ignore_git=True)

            if self.post_checkout_hook is not None:
                logger.info("Running post_checkout_hook on %s", staging_dir)
                self.post_checkout_hook(staging_dir)

            logger.info("Initializing fresh git repository in staging directory")
            initialize_git_repository(staging_dir)

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
            subprocess.run(
                ["git", "checkout", "-b", "dev"],
                cwd=staging_dir,
                check=True,
                capture_output=True,
            )
            logger.info("Created fresh git repo with 'main' and 'dev' branches")
        else:
            # Find the .git root by walking up from original_codebase.
            repo_root = original_codebase
            while repo_root.parent != repo_root:
                if (repo_root / ".git").exists():
                    break
                repo_root = repo_root.parent

            # Stale .git/index.lock files from a crashed prior run break checkout.
            logger.info("Removing git index lock files")
            git_dir = Path(repo_root) / ".git"
            if git_dir.exists():
                for lock_file in git_dir.rglob("index.lock"):
                    try:
                        lock_file.unlink()
                        logger.debug(f"Removed lock file: {lock_file}")
                    except Exception as e:
                        logger.warning(f"Failed to remove lock file {lock_file}: {e}")

            logger.info(f"Checking out commit {self.commit_id} in {original_codebase}")
            git_checkout(original_codebase, self.commit_id, force=True)

            logger.info(f"Copying {original_codebase} to {staging_dir}")
            self.copy_files(original_codebase, staging_dir, ignore_git=False)

            logger.info("Setting up dev branch in staging directory")
            git_setup_dev_branch(staging_dir)

            if self.post_checkout_hook is not None:
                logger.info("Running post_checkout_hook on %s", staging_dir)
                self.post_checkout_hook(staging_dir)

        if agent_codebase.exists():
            logger.info(f"Removing existing agent_codebase at {agent_codebase}")
            shutil.rmtree(agent_codebase, onerror=onerror)

        logger.info(f"Moving staging directory to {agent_codebase}")
        shutil.move(str(staging_dir), str(agent_codebase))
        logger.info("✓ Agent codebase ready for mounting")

        volumes = {str(agent_codebase): {"bind": "/app/codebase", "mode": "ro"}}

        return volumes

    def _setup_agent_apk(self) -> Optional[dict]:
        """Copy the built APK into a staging directory for the agent.

        The caller is the source of truth for which APK to stage — exploit
        passes the vuln APK, redteam passes the bundle's phase-1 APK.
        Returns a volume mapping to bind-mount at /app/apk/.
        """
        if self.apk_path is None:
            raise ValueError(
                "apk_path must be provided to setup_agent_environment when "
                "no_codebase=True"
            )
        apk_path = self.apk_path
        if not apk_path.exists():
            raise FileNotFoundError(
                f"APK not found at {apk_path}. "
                f"Build the APK first or set no_codebase=false in runner_config."
            )

        agent_apk_dir = self.app_dir / "agent_apk"
        if agent_apk_dir.exists():
            shutil.rmtree(agent_apk_dir)
        agent_apk_dir.mkdir(parents=True)

        shutil.copy2(apk_path, agent_apk_dir / apk_path.name)
        logger.info(f"Copied APK {apk_path.name} to agent_apk staging directory")

        return {str(agent_apk_dir): {"bind": "/app/apk", "mode": "ro"}}

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

        logger.info(f"Mounting agent_output at {OUTPUT_DIR}")
        return {
            str(agent_output_dir): {
                "bind": OUTPUT_DIR,
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
        # Do not force REQUESTS_CA_BUNDLE: requests.Session.verify=False is
        # otherwise overridden by trust_env=True, which breaks exploits that
        # intentionally disable verification for Docker/emulator hostnames.
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

            shutil.copytree(
                source,
                destination,
                dirs_exist_ok=True,
                ignore=ignore_func,
                symlinks=True,
            )

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
        with open(git_file, "r") as f:
            content = f.read().strip()

        if not content.startswith("gitdir:"):
            # Regular .git file — no submodule indirection; copy verbatim.
            shutil.copy2(git_file, destination / ".git")
            logger.debug(f"Copied .git file from {git_file} to {destination / '.git'}")
            return

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

        dest_git_path = destination / ".git"
        prepare_git_directory(dest_git_path)

        try:
            initialize_git_repository(destination)
            self._copy_git_directories(actual_git_dir, dest_git_path)
            self._copy_git_files(actual_git_dir, dest_git_path)
            self._create_clean_git_config(dest_git_path)
            logger.debug(f"Copied Git data from {actual_git_dir} to {dest_git_path}")

            # cleanup_git_branches promotes the detached HEAD to the new main.
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

            # cleanup_git_branches promotes the detached HEAD to the new main.
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

    def _save_container_dir(self, container_path: str, dest_dir: Path) -> None:
        """Copy a directory from the container to dest_dir.

        Works on a stopped container (Docker's ``get_archive`` reads the
        overlay filesystem). The previous ``ls`` precheck required a running
        container, which broke after the harness's SIGKILL timeout path
        (``container.kill(signal="SIGKILL")``). ``get_archive`` raises
        ``docker.errors.NotFound`` when the path is missing; that is the
        expected case for, e.g., agent_output when the agent never wrote
        anything, so we log it at INFO not WARNING.
        """
        dir_name = container_path.rstrip("/").split("/")[-1]
        if not self.container:
            logger.warning(f"No container available, cannot save {dir_name}")
            return

        try:
            bits, _ = self.container.get_archive(container_path)
        except docker.errors.NotFound:
            logger.info(f"No {dir_name} found in container")
            return
        except Exception as e:
            logger.warning(f"Failed to save {dir_name}: {e}")
            return

        try:
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
        self._save_container_dir(EXPLOIT_DIR, dest_dir)

    def save_agent_run(self, dest_dir: Path) -> None:
        """Copy /app/agent_run/ from the container to dest_dir/agent_run/.

        Carries the BYO-contract diagnostic trail: result.json,
        conversation.jsonl, agent.log. Pulled FIRST by ``run_agent``'s
        finally-block so the diagnostic trail survives even when other
        extractions fail.
        """
        self._save_container_dir(RUN_DIR, dest_dir)

    def save_agent_output(self, dest_dir: Path) -> None:
        """Copy /app/agent_output/ from the container to dest_dir/agent_output/."""
        self._save_container_dir(OUTPUT_DIR, dest_dir)

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
        firewall.stop()


def create_docker_network(
    network_name: str = SHARED_NET, internal: bool = False
) -> None:
    """Create a Docker network if absent.

    Fails hard if an existing network has ``Internal=False`` when the caller
    asked for ``internal=True`` — otherwise the kernel egress firewall would
    be silently defeated. The reverse mismatch only warns.
    """
    client = docker.from_env()
    try:
        existing = client.networks.get(network_name)
    except docker.errors.NotFound:
        client.networks.create(network_name, driver="bridge", internal=internal)
        logger.info(
            f"Created network '{network_name}'{' (internal)' if internal else ''}"
        )
        return

    actual_internal = existing.attrs.get("Internal", False)
    if internal and not actual_internal:
        raise RuntimeError(
            f"Network '{network_name}' exists with Internal=False; "
            f"this defeats the kernel egress firewall. "
            f"Remove it: `docker network rm {network_name}`."
        )
    if actual_internal != internal:
        logger.warning(
            f"Network '{network_name}' has Internal={actual_internal}, expected {internal}"
        )


def _start_adb_proxy() -> None:
    """Start the ADB filtering proxy sidecar.

    On agent_net so the agent reaches it; second foot on Docker's default
    bridge (host.docker.internal:host-gateway) so the proxy itself hairpins
    out to host's adbd. Filters ADB messages: blocks ``root:``, ``unroot:``,
    ``shell:su``, etc.
    """
    client = docker.from_env()
    _stop_adb_proxy()

    proxy_script = _REPO_ROOT / "utils" / "adb_filter_proxy.py"
    patterns_module = proxy_script.parent / "adb_blocked_patterns.py"
    for f in (proxy_script, patterns_module):
        if not f.exists():
            raise FileNotFoundError(f"ADB filter proxy source missing: {f}")

    proxy_container = client.containers.run(
        image=ADB_PROXY_IMAGE,
        name=ADB_PROXY_CONTAINER,
        command="python3 /opt/adb_filter_proxy.py",
        detach=True,
        network=AGENT_NET,
        extra_hosts={"host.docker.internal": "host-gateway"},
    )
    client.networks.get(EXTERNAL_BRIDGE).connect(proxy_container)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(str(proxy_script), arcname="adb_filter_proxy.py")
        tar.add(str(patterns_module), arcname="adb_blocked_patterns.py")
    buf.seek(0)
    proxy_container.put_archive("/opt", buf)
    # Restart so the interpreter reads the script that was copied in after start.
    proxy_container.restart()
    logger.info(f"ADB proxy started (:{ADB_PROXY_PORT} → host adbd)")


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
        # adb root is required to bind-mount over /system/xbin/su below.
        subprocess.run(["adb", "root"], capture_output=True, timeout=10)
        subprocess.run(["adb", "wait-for-device"], capture_output=True, timeout=30)

        # Mask the su binary with an empty mode-000 file so it can't execute
        # even if the agent bypasses the adb-proxy filter.
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

        subprocess.run(["adb", "unroot"], capture_output=True, timeout=10)
    except Exception as e:
        logger.warning(f"Failed to fully disable emulator root: {e}")
        # Still try to unroot even if bind mount failed
        try:
            subprocess.run(["adb", "unroot"], capture_output=True, timeout=10)
        except Exception:
            pass


# Auth tokens forwarded from operator's .env to every agent container. The
# in-container CLI reads what it needs and ignores the rest; missing values
# stay missing (we log names — not values — at setup).
AUTH_ENV_PASSTHROUGH = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "OPENCODE_AUTH_CONTENT",
    "OPENCODE_OPENAI_AUTH",
)


def setup_agent_environment(
    app_dir: Path,
    agent_image: str,
    metadata: dict,
    network_mode: str,
    workflow: str = "exploit",
    vuln_id: Optional[str] = None,
    no_codebase: bool = False,
    post_checkout_hook: Optional[Callable[[Path], None]] = None,
    apk_path: Optional[Path] = None,
) -> AgentEnvironment:
    """
    Set up the agent environment container.

    Args:
        app_dir: Application directory
        agent_image: Docker image to use for agent (custom = kali base;
            external = BYO reference image)
        metadata: App metadata dict
        workflow: Evaluation workflow type ("exploit" or "redteam")
        vuln_id: Vulnerability ID for exploit workflow
        network_mode: Squid policy ("permissive" default, or "restricted")
        no_codebase: Whether to copy the built APK into the agent environment
        post_checkout_hook: Optional callback run on the staged codebase
        apk_path: APK to copy into the agent environment when no_codebase=True

    Returns:
        AgentEnvironment instance
    """
    # Networks are created earlier in preflight; don't re-create here.
    _start_adb_proxy()
    firewall.start(network_mode)

    _disable_emulator_root()
    logger.info("Emulator root privileges disabled")

    # Ensure agent/.env is loaded so auth tokens are picked up. Do not
    # ``override=True`` — shell-exported tokens beat dotfile values so an
    # operator who runs ``OPENAI_API_KEY=… python runner.py …`` gets what
    # they typed, not whatever the file contains.
    from dotenv import load_dotenv

    agent_env_file = _REPO_ROOT / "agent" / ".env"
    if agent_env_file.exists():
        load_dotenv(agent_env_file)

    # ADB → adb-proxy sidecar; HTTP/HTTPS → Squid; in-cluster targets bypass
    # via NO_PROXY (Python HTTP clients match by hostname suffix, not CIDR).
    egress_url = firewall.proxy_url()
    no_proxy = firewall.build_no_proxy(metadata, extra_aliases=[ADB_PROXY_CONTAINER])
    env_vars = {
        "ANDROID_ADB_SERVER_PORT": "5037",
        "ADB_SERVER_SOCKET": f"tcp:{ADB_PROXY_CONTAINER}:{ADB_PROXY_PORT}",
        "AGENT_SERVER_PORT": str(AGENT_HOST_PORT),
        "HTTPS_PROXY": egress_url,
        "HTTP_PROXY": egress_url,
        "https_proxy": egress_url,
        "http_proxy": egress_url,
        "NO_PROXY": no_proxy,
        "no_proxy": no_proxy,
    }

    # Forward whichever auth tokens the operator has set. CLI in-container
    # picks the one it needs; absent values are silently skipped.
    forwarded = []
    for name in AUTH_ENV_PASSTHROUGH:
        val = os.environ.get(name)
        if val:
            env_vars[name] = val
            forwarded.append(name)
    logger.info("Forwarded auth env vars: %s", ", ".join(forwarded) or "(none)")

    commit_id: Optional[str] = None
    if not no_codebase:
        from utils.metadata_utils import get_metadata_commit

        commit_id = get_metadata_commit(metadata)

    agent_env = AgentEnvironment(
        app_dir=app_dir,
        docker_networks=[AGENT_NET],
        image_name=agent_image,
        env=env_vars,
        commit_id=commit_id,
        workflow=workflow,
        package_name=metadata.get("package_name"),
        vuln_id=vuln_id if workflow == "exploit" else None,
        include_git_history=(workflow != "exploit"),
        no_codebase=no_codebase,
        post_checkout_hook=post_checkout_hook,
        apk_path=apk_path,
    )

    agent_env.setup()

    return agent_env
