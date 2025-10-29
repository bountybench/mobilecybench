import logging
import os
import shutil
import subprocess
import sys
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
    ):
        self.app_dir = app_dir
        self.app_name = app_dir.name
        self.docker_networks = docker_networks
        self.image_name = image_name
        self.env = env
        self.commit_id = commit_id

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
        # Use app_name as experiment_id for container naming to ensure isolation
        container_name = f"kali-container-{self.app_name}"

        print(f"Checking for image {self.image_name}...")
        logger.info(f"Ensuring image {self.image_name} is available...")
        try:
            seen_statuses = set()
            pulling_started = False

            for line in self.client.api.pull(self.image_name, stream=True, decode=True):
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

        # Remove existing container with the same name if it exists
        # TODO: long term fix is to append random id to container so it
        try:
            existing_container = self.client.containers.get(container_name)
            logger.info(f"Removing existing container: {container_name}")
            existing_container.remove(force=True)
        except docker.errors.NotFound:
            # no need to raise if container doesn't exist
            pass

        environment = self.env
        extra_hosts = {"host.docker.internal": "host-gateway"}
        command = '/bin/bash -c "while true; do sleep 30; done"'
        network = self.docker_networks[0] if self.docker_networks else None

        # Setup agent codebase and get volume mapping
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

    def _setup_agent_codebase(self):
        """Create a copy of codebase, prune all branches / future commits, copy into agent env"""
        original_codebase = self.app_dir / "codebase"
        agent_codebase = self.app_dir / "agent_codebase"

        # Check if agent_codebase exists and validate it
        if agent_codebase.exists():
            logger.info(f"Found existing agent_codebase at {agent_codebase}")
            if not self._validate_agent_codebase(agent_codebase):
                logger.warning("Validation failed, recreating agent_codebase")
                shutil.rmtree(agent_codebase)
            else:
                logger.info("Validation passed, using existing agent_codebase")
                return {str(agent_codebase): {"bind": "/app/codebase", "mode": "rw"}}

        # Check if original_codebase is empty, if so use git_submodule_update
        if not original_codebase.exists() or not any(original_codebase.iterdir()):
            logger.info("Original codebase is empty, initializing submodule")
            git_submodule_update(self.app_dir)

        # Find the repository root (which contains .git)
        repo_root = original_codebase
        while repo_root.parent != repo_root:
            if (repo_root / ".git").exists():
                break
            repo_root = repo_root.parent

        # Remove git index lock
        logger.info("Removing git index lock files")
        subprocess.run(
            [
                "find",
                ".git",
                "-type",
                "f",
                "-name",
                "index.lock",
                "-exec",
                "rm",
                "-f",
                "{}",
                ";",
            ],
            cwd=str(repo_root),
            stdout=sys.stdout,
            stderr=sys.stderr,
            check=True,
            text=True,
        )

        # Checkout to commit_id in original_codebase
        logger.info(f"Checking out commit {self.commit_id} in {original_codebase}")
        git_checkout(original_codebase, self.commit_id, force=True)

        # Create agent_codebase directory
        logger.info(f"Creating agent_codebase directory at {agent_codebase}")
        agent_codebase.mkdir(parents=True, exist_ok=True)

        # Copy original_codebase to agent_codebase with ignore_git=False
        logger.info(f"Copying {original_codebase} to {agent_codebase}")
        self.copy_files(original_codebase, agent_codebase, ignore_git=False)

        # Run git_setup_dev_branch
        logger.info("Setting up dev branch in agent_codebase")
        git_setup_dev_branch(agent_codebase)

        logger.info(f"Agent codebase setup complete at {agent_codebase}")

        # Return volume mapping for bind mount
        return {str(agent_codebase): {"bind": "/app/codebase", "mode": "rw"}}

    def _validate_agent_codebase(self, agent_codebase: Path) -> bool:
        """Validate that agent_codebase is properly set up.

        This function will be implemented later to check:
        - Branches are properly set up
        - Future commits are not reachable
        - Commit id matches
        """
        # TODO: Implement validation
        return True

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
