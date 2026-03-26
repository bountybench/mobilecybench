import docker

# Initializing important variables and containers
DOCKER_CLIENT = docker.from_env()
KALI_CONTAINER_NAME = "kali-container"
# All agent ADB traffic goes through the filtering proxy on shared_net.
# Kali cannot resolve host.docker.internal (no extra_hosts) so this is
# the only reachable ADB endpoint.
HOST_ADB_SERVER = "adb-proxy:5037"
AGENT_HOST_PORT = 9999


def get_kali():
    return DOCKER_CLIENT.containers.get(KALI_CONTAINER_NAME)
