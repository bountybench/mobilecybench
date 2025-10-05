# MobileCybench Orchestrator Container (Docker-in-Docker)

The MobileCybench orchestrator provides a consistent runtime environment for experiment execution at scale using Docker-in-Docker (DinD), similar to BountyBench.

## Architecture Overview

### Container Types

1. **Orchestrator Container** (`Dockerfile.orchestrator`)
   - Main container for running experiments
   - Includes Docker-in-Docker capability
   - Pre-installed dependencies for building apps
   - Mounts codebase as volume for fast iteration

2. **Backend Container** (`Dockerfile.backend`) - Optional
   - Simplified container for Android emulator
   - No Docker-in-Docker capability
   - Used when orchestration isn't needed

### Key Design Principles

- **Volume Mounting**: Codebase is mounted (not COPYed) to avoid rebuilds on code changes
- **Docker-in-Docker**: Orchestrator manages experiment containers internally
- **Pre-installed Dependencies**: All build tools and SDKs pre-installed for consistency
- **Complete Isolation**: No access to host Docker daemon

## Quick Start

### Automated (Recommended)

Run everything with a single command:

```bash
# From project root - handles build, start, and run automatically
./docker/run_experiment.sh audiobookshelf

# With custom config
./docker/run_experiment.sh owncloud-android custom_config.json

# Keep container running after experiment
./docker/run_experiment.sh audiobookshelf --keep-running
```

The script automatically:
- Builds container (if needed)
- Starts Docker-in-Docker
- Waits for readiness
- Runs the experiment
- Shows live output
- Cleans up (unless --keep-running)

### Manual (Advanced)

For more control:

```bash
# 1. Build orchestrator
docker compose build orchestrator

# 2. Start orchestrator
docker compose up -d orchestrator

# 3. Run experiment inside container
docker exec -it mobilecybench-orchestrator bash
cd /mobilecybench
./setup.sh owncloud-android
./start_emulator.sh --yes
python3 runner.py owncloud-android

# 4. Stop
docker compose down
```

## Container Hierarchy

```
Host Docker Daemon
└── mobilecybench-orchestrator (privileged)
    ├── Docker Daemon (running inside)
    ├── Android Emulator
    └── Child Containers (spawned internally)
        ├── kali-agent-1
        ├── kali-agent-2
        ├── app-db
        └── app-server
```

**Note**: Run `docker ps` on host → see only `mobilecybench-orchestrator`
Run `docker ps` inside orchestrator → see all child containers

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
docker logs mobilecybench-orchestrator | grep -i docker
docker exec mobilecybench-orchestrator docker info
docker exec mobilecybench-orchestrator tail -f /var/log/dockerd.log
```

### View Child Containers

```bash
docker exec mobilecybench-orchestrator docker ps
```

### Emulator Performance

Ensure KVM is enabled on host:

```bash
lsmod | grep kvm
sudo usermod -aG kvm $USER  # then logout/login
```

## Useful Commands

```bash
# Logs
docker logs -f mobilecybench-orchestrator

# Check internal Docker
docker exec mobilecybench-orchestrator docker info
docker exec mobilecybench-orchestrator docker ps

# Shell access
docker exec -it mobilecybench-orchestrator bash

# Stop
docker compose down orchestrator
```
