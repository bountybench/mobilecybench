import docker

# Initializing important variables and containers
DOCKER_CLIENT = docker.from_env()
KALI_CONTAINER_NAME = "kali-container"
HOST_ADB_SERVER = "host.docker.internal:5037"


def get_kali(experiment_id: str):
    """Get Kali container by experiment_id"""
    # Use experiment_id to find the specific container for this experiment
    container_name = f"kali-container-{experiment_id}"
    try:
        return DOCKER_CLIENT.containers.get(container_name)
    except docker.errors.NotFound:
        # Fallback to default container if experiment-specific one doesn't exist
        return DOCKER_CLIENT.containers.get(KALI_CONTAINER_NAME)
