import logging
import subprocess
from pathlib import Path
from typing import Dict, List

import docker
import docker.errors

logger = logging.getLogger(__name__)


class AgentEnvironment:
    def __init__(
        self,
        app_dir: Path,
        docker_networks: List[str],
        image_name: str,
        env: Dict[str, str],
    ):
        self.app_dir = app_dir
        self.app_name = app_dir.name
        self.docker_networks = docker_networks
        self.image_name = image_name
        self.env = env

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
            pass

        environment = self.env
        extra_hosts = {"host.docker.internal": "host-gateway"}
        command = '/bin/bash -c "while true; do sleep 30; done"'
        network = self.docker_networks[0] if self.docker_networks else None

        self.container = self.client.containers.run(
            image=self.image_name,
            name=container_name,
            command=command,
            environment=environment,
            extra_hosts=extra_hosts,
            network=network,
            stdin_open=True,
            tty=True,
            detach=True,
        )

        # Connect to additional networks if any
        for additional_network in self.docker_networks[1:]:
            network_obj = self.client.networks.get(additional_network)
            network_obj.connect(self.container)

        # Copy codebase to container
        self._copy_codebase()

    def _copy_codebase(self):
        """Copy app codebase to Kali container."""
        source_path = self.app_dir / "codebase"
        target_path = "/app/codebase"

        if not source_path.exists():
            logger.error(f"Codebase directory not found: {source_path}")
            logger.error("Check if submodules are initialized")
            return

        logger.info(
            f"Copying from {source_path} to {self.container.name}:{target_path}"
        )

        try:
            # Create target directory in container
            exit_code, output = self.container.exec_run(f"mkdir -p {target_path}")
            if exit_code != 0:
                logger.warning(
                    f"Could not create directory in container: {output.decode()}"
                )
                return

            # Copy files to container using docker cp
            subprocess.run(
                f"docker cp {source_path}/. {self.container.name}:{target_path}/",
                shell=True,
                check=True,
            )
            logger.info(f"Codebase copied successfully to {target_path}")

        except Exception as e:
            logger.error(f"Failed to copy codebase: {e}")

    def teardown(self):
        if not self.container:
            logger.warning("No container to tear down")
            return

        try:
            logger.info(f"Stopping container {self.container.name}")
            self.container.stop()
            logger.info(f"Removing container {self.container.name}")
            self.container.remove()
            logger.info(f"Container {self.container.name} removed successfully")
            self.container = None
        except Exception as e:
            logger.error(f"Failed to tear down container: {e}")
