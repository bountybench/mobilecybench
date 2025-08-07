import docker

#Initializing important variables and containers
DOCKER_CLIENT = docker.from_env()
KALI_CONTAINER_NAME = "kali-container"
HOST_ADB_SERVER = "host.docker.internal:5037"

def get_kali():
    return DOCKER_CLIENT.containers.get(KALI_CONTAINER_NAME)