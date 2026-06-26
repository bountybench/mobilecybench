import docker

# Initializing important variables and containers
DOCKER_CLIENT = None
KALI_CONTAINER_NAME = "kali-container"
AGENT_HOST_PORT = 9999


def get_kali():
    global DOCKER_CLIENT
    if DOCKER_CLIENT is None:
        DOCKER_CLIENT = docker.from_env()
    return DOCKER_CLIENT.containers.get(KALI_CONTAINER_NAME)
