import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List

import docker
import docker.errors

from utils.git_utils import (
    cleanup_git_branches,
    git_checkout,
    git_setup_dev_branch,
    git_submodule_update,
    initialize_git_repository,
    onerror,
    prepare_git_directory,
)

logger = logging.getLogger(__name__)


class AgentEnvironment:
    def __init__(
        self,
        app_dir: Path,
        docker_networks: List[str],
        image_name: str,
        env: Dict[str, str],
        commit_id: str,
        mode: str = None,
        synthetic_vuln: bool = False,
    ):
        self.app_dir = app_dir
        self.app_name = app_dir.name
        self.docker_networks = docker_networks
        self.image_name = image_name
        self.env = env
        self.commit_id = commit_id
        self.mode = mode
        self.synthetic_vuln = synthetic_vuln

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

        environment = self.env
        extra_hosts = {"host.docker.internal": "host-gateway"}
        command = '/bin/bash -c "while true; do sleep 30; done"'
        network = self.docker_networks[0] if self.docker_networks else None

        # Setup agent codebase and get volume mapping
        volumes = None
        try:
            volumes = self._setup_agent_codebase()

            self.container = self.client.containers.run(
                image=self.image_name,
                name=container_name,
                command=command,
                environment=environment,
                extra_hosts=extra_hosts,
                network=network,
                volumes=volumes,
                stdin_open=True,
                tty=True,
                detach=True,
            )

            # Connect to additional networks if any
            for additional_network in self.docker_networks[1:]:
                network_obj = self.client.networks.get(additional_network)
                network_obj.connect(self.container)

            # Create exploit_files directory
            logger.info("Creating exploit_files directory in container")
            self.container.exec_run("mkdir -p /app/exploit_files")

            if self.mode == "codex":
                logger.info("Logging in to Codex CLI with API key...")
                result = self.container.exec_run(
                    "bash -c 'echo $CODEX_API_KEY | codex login --with-api-key'"
                )
                if result.exit_code == 0:
                    logger.info("Codex CLI logged in successfully")
                else:
                    logger.error(f"Codex login failed: {result.output.decode()}")

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

        Normal mode: Checkout specific commit, copy with git history.
        Synthetic vulnerability mode: Copy current state (with patch applied),
        no git history to prevent agent from seeing the patch was applied.
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

        if self.synthetic_vuln:
            # Synthetic vulnerability mode: copy current state without git history
            logger.info(
                "Synthetic vuln mode: Copying current codebase state without git history"
            )
            # Copy files but ignore .git to prevent agent from seeing patch history
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
            # Normal mode: checkout specific commit and preserve git history
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

        # Copy pre-generated static vulnerability reports into staging directory if in supervisor mode
        if self.mode == "supervisor":
            static_reports_src = self.app_dir / "static_vuln_reports"
            static_reports_dest = staging_dir / "static_vuln_reports"
            if static_reports_src.exists():
                logger.info(
                    f"Copying static vulnerability reports from {static_reports_src} to {static_reports_dest}"
                )
                shutil.copytree(
                    static_reports_src, static_reports_dest, dirs_exist_ok=True
                )
                logger.info(
                    "✓ Copied static vulnerability reports into staging directory"
                )
            else:
                logger.warning(
                    "static_vuln_reports directory not found; supervisor agents will not see pre-generated static reports"
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
        return {str(agent_codebase): {"bind": "/app/codebase", "mode": "rw"}}

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

    def save_agent_codebase_state(self) -> str:
        """Save the current state of agent_codebase by capturing git diff.

        This captures:
        - Modified files (tracked changes)
        - New files (untracked files)
        - Deleted files

        Returns:
            The git diff output as a string, or empty string if no changes.
        """
        agent_codebase = self.app_dir / "agent_codebase"

        if not agent_codebase.exists():
            logger.warning("agent_codebase does not exist, nothing to save")
            return ""

        try:
            # Add all changes to staging area (including untracked files)
            # Exclude static analysis inputs provided externally
            result = subprocess.run(
                [
                    "git",
                    "add",
                    "-A",
                    "--",
                    ".",
                    ":!semgrep_results.json",
                    ":!static_vuln_reports/**",
                    ":!static_vuln_reports",
                ],
                cwd=agent_codebase,
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info(
                "Added all changes to staging area in agent_codebase (excluding external static analysis inputs)"
            )

            # Get the diff between HEAD and staged changes
            # This will now include all tracked modifications AND new files
            result = subprocess.run(
                ["git", "diff", "--cached"],
                cwd=agent_codebase,
                capture_output=True,
                text=True,
                check=True,
            )

            diff_output = result.stdout
            if diff_output:
                logger.info(
                    f"Captured git diff from agent_codebase ({len(diff_output)} chars)"
                )
            else:
                logger.info("No changes detected in agent_codebase")

            return diff_output

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to save agent_codebase state: {e}")
            logger.error(f"stderr: {e.stderr}")
            return ""
        except Exception as e:
            logger.error(f"Unexpected error saving agent_codebase state: {e}")
            return ""

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
