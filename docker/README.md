# MobileCybench Backend Container (Docker-in-Docker)

The MobileCybench backend container provides a unified runtime environment for both API services and experiment orchestration using Docker-in-Docker (DinD), similar to BountyBench.

## Architecture Overview

### Unified Backend Design
The backend container combines:
1. **API Server**: Handles API requests (port 7999)
2. **Experiment Orchestrator**: Runs Android emulator and spawns child containers

### Docker-in-Docker (DinD)
- **Internal Docker Daemon**: Runs `dockerd` inside the backend container
- **Child Containers**: All agent and app backend containers spawn as nested containers
- **Complete Isolation**: No access to host Docker daemon

## Quick Start

```bash
# 1. Build
docker compose build backend

# 2. Start
docker compose up -d backend

# 3. Run experiment
docker exec -it mobilecybench-backend bash
cd /mobilecybench
./setup.sh owncloud-android
./start_emulator.sh --yes
python3 runner.py owncloud-android
```

## Container Hierarchy

```
Host Docker Daemon
└── mobilecybench-backend (privileged)
    ├── Docker Daemon (running inside)
    ├── Android Emulator
    └── Child Containers (spawned internally)
        ├── kali-agent-1
        ├── kali-agent-2
        ├── app-db
        └── app-server
```

**Note**: Run `docker ps` on host → see only `mobilecybench-backend`
Run `docker ps` inside backend → see all child containers

## Configuration

### Volumes
- `dind-data:/var/lib/docker` - Docker daemon storage (create with `docker volume create dind-data`)
- `./:/mobilecybench:rw` - Live code mounting
- `gradle-cache:/root/.gradle` - Gradle cache
- `./logs` and `./results` - Experiment outputs

### Ports
- 7999: Backend API
- 5037: ADB server
- 5554-5555: Emulator console/ADB
- 5900: VNC server

### Environment Variables
Copy `.env.example` to `.env`:
```bash
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
```

## Troubleshooting

### Docker Daemon Not Starting
```bash
docker logs mobilecybench-backend | grep -i docker
docker exec mobilecybench-backend docker info
docker exec mobilecybench-backend tail -f /var/log/dockerd.log
```

### View Child Containers
```bash
docker exec mobilecybench-backend docker ps
```

### Emulator Performance
Ensure KVM is enabled on host:
```bash
lsmod | grep kvm
sudo usermod -aG kvm $USER  # then logout/login
```

## Migration from Old Orchestrator

Replace:
- `mobilecybench-orchestrator` → `mobilecybench-backend`
- `docker-compose.orchestrator.yml` → `docker-compose.yml`
- `./docker/build_orchestrator.sh` → `docker compose build backend`
- `./docker/start_orchestrator.sh` → `docker compose up -d backend`

See [ARCHITECTURE_CHANGE.md](../ARCHITECTURE_CHANGE.md) for details.

## Useful Commands

```bash
# Logs
docker logs -f mobilecybench-backend

# Check internal Docker
docker exec mobilecybench-backend docker info
docker exec mobilecybench-backend docker ps

# Shell access
docker exec -it mobilecybench-backend bash

# Stop
docker compose down backend
```
