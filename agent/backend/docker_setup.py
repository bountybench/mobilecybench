import docker
from functools import lru_cache

KALI_CONTAINER_NAME = "kali-container"
# TODO: In container emulator mode, both the agent and emulator containers are
# on shared_net, so the agent could connect directly to emulator-container:5037
# instead of bouncing through the host (agent → host → emulator container).
# Once the agent path is direct, the host port 5037 mapping is still needed
# for host-side scripts (inject_system_ca.sh, start_runtime.sh) that use
# bare `adb`. Eliminating the mapping entirely requires routing those through
# docker exec too.
HOST_ADB_SERVER = "host.docker.internal:5037"
AGENT_HOST_PORT = 9999


@lru_cache(maxsize=1)
def get_docker_client():
    return docker.from_env()


def get_kali():
    return get_docker_client().containers.get(KALI_CONTAINER_NAME)
