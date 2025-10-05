# MobileCybench Architecture Change

## Summary

MobileCybench has been refactored to use a unified architecture similar to BountyBench:

### Before (Old Architecture)
- **Separate containers**: `Dockerfile.orchestrator` + `Dockerfile.backend`
- **Two services**: orchestrator for running experiments, backend for API
- **docker-compose.orchestrator.yml**: Separate compose file for orchestrator

### After (New Architecture) ✨
- **Single unified container**: `Dockerfile.backend` (combines both roles)
- **One service**: backend acts as both API server and experiment orchestrator
- **docker-compose.yml**: Single compose file for the unified service
- **Docker-in-Docker (DinD)**: Backend runs Docker daemon internally
- **Child containers**: All agent and app containers spawn from within backend

## Key Changes

### 1. **Dockerfile.backend** (Enhanced)
- Includes Android SDK, emulator, and all orchestration tools
- Includes KVM support, VNC, X11 for emulator
- Runs Docker daemon via `dockerd_entrypoint.sh`
- Exposes ports: 7999 (API), 5037 (ADB), 5554-5555 (Emulator), 5900 (VNC)

### 2. **docker-compose.yml** (Updated)
- Single `backend` service with all orchestration capabilities
- Privileged mode + DinD volume (`dind-data:/var/lib/docker`)
- Security options: `seccomp:unconfined` for emulator compatibility
- Resource limits: 4 CPUs, 8GB memory (adjustable)
- All Android and emulator environment variables

### 3. **Archived Files** (Moved to `archive/orchestrator/`)
- `Dockerfile.orchestrator`
- `docker-compose.orchestrator.yml`
- `ORCHESTRATOR_SETUP.md`
- `docker/orchestrator-entrypoint.sh`
- `docker/build_orchestrator.sh`
- `docker/start_orchestrator.sh`
- `docker/stop_orchestrator.sh`

## How to Use

### Building
```bash
# Build the unified backend image
docker compose build backend
```

### Running
```bash
# Start the backend container
docker compose up -d backend

# Exec into the container
docker exec -it mobilecybench-backend bash

# Inside container: run experiments as before
cd /mobilecybench
./setup.sh <app_name>
./start_emulator.sh --yes
python3 runner.py <app_name>
```

### Container Spawning
All child containers (Kali agents, app backends) are spawned using the Docker daemon running **inside** the backend container:
- Uses `docker.from_env()` which connects to the internal Docker daemon
- Child containers run as nested containers within the backend
- Complete isolation from host Docker

## Benefits

1. **Simplified architecture**: One service instead of two
2. **Consistency with BountyBench**: Both projects now use the same pattern
3. **Better isolation**: True Docker-in-Docker (no sibling containers)
4. **Easier deployment**: Single `docker-compose.yml` to manage
5. **Resource efficiency**: Shared environment for API and orchestration

## Migration Notes

- Replace `mobilecybench-orchestrator` with `mobilecybench-backend` in all commands
- Use `docker-compose.yml` instead of `docker-compose.orchestrator.yml`
- All scripts and functionality work the same, just run inside the backend container
- Old orchestrator files preserved in `archive/orchestrator/` for reference
