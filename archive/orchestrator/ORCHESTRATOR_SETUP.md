# MobileCybench Orchestrator Setup

This document summarizes the Orchestrator container implementation for MobileCybench.

## Overview

The Orchestrator container provides a consistent, reproducible runtime environment for running MobileCybench experiments at scale, similar to BountyBench's approach but with significant improvements.

## Key Improvements Over BountyBench

1. **Live Code Mounting**
   - BountyBench: Copies entire codebase into image → slow iteration (rebuild for each change)
   - MobileCybench: Mounts codebase as volume → instant code changes, no rebuild needed

2. **Android Emulator Support**
   - Added full Android emulator support with KVM hardware acceleration
   - Pre-installed Android SDK with multiple versions (34, 35)
   - Optimized for running experiments in containerized environment

3. **Better Development Experience**
   - Volume mounts for live code updates
   - Persistent results and logs directories
   - Helper scripts for common operations

## Files Created

### Core Files

1. **Dockerfile.orchestrator**
   - Base: Ubuntu 22.04
   - Includes: Android SDK, Java 17, Python 3, Docker, all dependencies
   - Pre-installs: Android SDK 34 & 35, build tools, emulator

2. **docker-compose.orchestrator.yml**
   - Configures orchestrator service
   - Sets up volume mounts (codebase, Docker socket, KVM device)
   - Defines networks (mobilecybench-net, shared_net)
   - Resource limits (4 CPU, 8GB RAM default)

3. **docker/orchestrator-entrypoint.sh**
   - Container initialization script
   - Starts ADB server
   - Validates environment setup
   - Displays status information

### Helper Scripts

4. **docker/build_orchestrator.sh**
   - Builds the orchestrator Docker image
   - Creates shared_net network if needed

5. **docker/start_orchestrator.sh**
   - Starts the orchestrator container using docker-compose
   - Loads environment variables from .env
   - Checks for KVM support

6. **docker/stop_orchestrator.sh**
   - Stops and removes the orchestrator container

7. **docker/run_experiment.sh**
   - Convenience script to run complete experiments
   - Handles setup, emulator start, and runner execution

### Documentation

8. **docker/README.md**
   - Comprehensive orchestrator documentation
   - Usage examples
   - Troubleshooting guide
   - Architecture details

9. **.dockerignore**
   - Optimizes Docker build context
   - Excludes build artifacts, logs, test files

10. **README.md updates**
    - Added "Orchestrator Container (For Scale)" section
    - Quick start guide
    - Comparison table (Local vs Orchestrator)

## Usage

### Basic Workflow

```bash
# One-time setup
./docker/build_orchestrator.sh

# Start container
./docker/start_orchestrator.sh

# Run experiment
./docker/run_experiment.sh owncloud-android

# Stop container
./docker/stop_orchestrator.sh
```

### Manual Workflow

```bash
# Start container
./docker/start_orchestrator.sh

# Exec into container
docker exec -it mobilecybench-orchestrator bash

# Inside container:
./setup.sh owncloud-android
./start_emulator.sh
python3 runner.py owncloud-android runner_config.json
```

## Architecture

```
Host Machine
├── mobilecybench/                    (your code)
│   ├── apps/
│   ├── runner.py
│   └── ...
│
└── Docker Container (orchestrator)
    ├── /mobilecybench/               (mounted from host)
    ├── /opt/android-sdk/             (pre-installed)
    │   ├── platform-tools/
    │   ├── emulator/
    │   └── platforms/
    └── /var/run/docker.sock          (mounted from host)
```

## Key Design Decisions

### 1. Volume Mounting vs Copying

**Decision**: Mount codebase as volume instead of copying into image

**Rationale**:
- BountyBench copied code → required rebuild for every code change → slow iteration
- Volume mounting allows instant code reflection → fast development
- Trade-off: Slightly more complex setup, but much better DX

### 2. Docker-in-Docker

**Decision**: Mount host Docker socket into container

**Rationale**:
- App backends run as Docker containers
- Need to start/stop containers from within orchestrator
- Alternative (Docker-outside-of-Docker) works but requires socket mounting anyway

### 3. KVM Support

**Decision**: Mount /dev/kvm for hardware acceleration

**Rationale**:
- Android emulator is very slow without hardware acceleration
- KVM provides near-native performance
- Falls back gracefully if KVM not available (with warning)

### 4. Multi-SDK Support

**Decision**: Pre-install multiple Android SDK versions

**Rationale**:
- Different apps target different SDK versions
- Pre-installing avoids runtime downloads
- Increases image size but improves experiment startup time

## Running at Scale

### Parallel Experiments

```bash
# Start multiple orchestrators
docker-compose -f docker-compose.orchestrator.yml -p exp1 up -d
docker-compose -f docker-compose.orchestrator.yml -p exp2 up -d
docker-compose -f docker-compose.orchestrator.yml -p exp3 up -d

# Run different experiments
docker exec exp1-orchestrator-1 python3 runner.py owncloud-android
docker exec exp2-orchestrator-1 python3 runner.py conversations
docker exec exp3-orchestrator-1 python3 runner.py wordpress
```

### CI/CD Integration

```yaml
# GitHub Actions example
- name: Build Orchestrator
  run: ./docker/build_orchestrator.sh

- name: Run Experiments
  run: |
    ./docker/start_orchestrator.sh
    ./docker/run_experiment.sh ${{ matrix.app }}
```

## Requirements

### Host System

- Linux (Ubuntu 22.04+ recommended)
- Docker 20.10+
- Docker Compose 2.0+
- KVM support (check with `kvm-ok`)
- 8GB+ RAM
- 20GB+ disk space

### Permissions

```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Add user to kvm group
sudo usermod -aG kvm $USER

# Logout and login for changes to take effect
```

## Troubleshooting

### Issue: KVM not found

```bash
# Check KVM support
ls -l /dev/kvm

# If missing, enable virtualization in BIOS
# Then install KVM
sudo apt install qemu-kvm libvirt-daemon-system
```

### Issue: Docker socket permission denied

```bash
# Check Docker group membership
groups

# If docker not in list:
sudo usermod -aG docker $USER
# Then logout/login
```

### Issue: Code changes not reflected

```bash
# Verify volume mount
docker inspect mobilecybench-orchestrator | grep -A 10 Mounts

# Should show:
# "Source": "/path/to/mobilecybench"
# "Destination": "/mobilecybench"
# "Mode": "rw"
```

## Future Enhancements

### Potential Improvements

1. **Kubernetes Support**
   - Convert to Kubernetes deployments
   - Enable massive parallel execution

2. **Build Cache Optimization**
   - Cache Android build artifacts between runs
   - Reduce app build times

3. **Remote Execution**
   - Support for running on remote machines
   - Distributed experiment execution

4. **Monitoring & Metrics**
   - Built-in monitoring dashboards
   - Resource usage tracking

5. **Auto-scaling**
   - Dynamically create/destroy containers based on workload
   - Queue management for experiments

## Comparison with BountyBench

| Feature | BountyBench | MobileCybench Orchestrator |
|---------|-------------|----------------------------|
| Codebase Handling | Copied into image | Mounted as volume |
| Code Change Speed | Slow (rebuild) | Fast (instant) |
| Android Emulator | Not supported | Full support + KVM |
| Multi-SDK | Single SDK | Multiple versions |
| App Backends | External | Docker-in-Docker |
| Development UX | Poor | Excellent |
| CI/CD Ready | Yes | Yes |
| Parallel Execution | Manual | Easy |

## Testing Checklist

Before considering the orchestrator production-ready, test:

- [ ] Image builds successfully
- [ ] Container starts without errors
- [ ] ADB server starts correctly
- [ ] KVM device is accessible (if available)
- [ ] Docker socket is mounted and accessible
- [ ] Code changes on host appear in container
- [ ] Android emulator starts successfully
- [ ] App backend containers can be started
- [ ] Experiments complete successfully
- [ ] Results are persisted to host
- [ ] Logs are persisted to host
- [ ] Multiple orchestrators can run in parallel
- [ ] Container stops cleanly

## Conclusion

The MobileCybench Orchestrator provides a robust, scalable solution for running experiments in a consistent environment. By addressing BountyBench's limitation of requiring rebuilds for code changes, it significantly improves the development experience while maintaining all the benefits of containerization.

The architecture supports both development (fast iteration) and production (consistent, scalable execution) use cases, making it suitable for experimentation at any scale.
