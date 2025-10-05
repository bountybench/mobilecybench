# MobileCybench Orchestrator Container

The Orchestrator container provides a consistent, reproducible runtime environment for running MobileCybench experiments at scale. It packages all necessary dependencies including Android SDK, emulator, and build tools.

## Key Improvements over BountyBench

1. **Live Code Mounting**: The entire codebase is mounted as a volume (not copied), so code changes don't require container rebuilds
2. **Hardware Acceleration**: Supports KVM for faster emulator performance
3. **Docker-in-Docker**: Runs its own Docker daemon inside the container - all app backends run INSIDE the orchestrator
4. **Multi-SDK Support**: Pre-installed SDK versions 34 and 35 to support different apps

## Prerequisites

- Docker and Docker Compose installed
- Linux host with KVM support (for hardware acceleration)
  - Check KVM support: `kvm-ok` or `lsmod | grep kvm`
  - Enable KVM access: `sudo usermod -aG kvm $USER` (then logout/login)
- At least 8GB RAM available
- At least 20GB disk space

**Note on Architecture:** The Dockerfile automatically detects your system architecture and installs the appropriate Android system images:
- **ARM64 (Apple Silicon)**: Uses `arm64-v8a` system images
- **x86_64 (Intel/AMD)**: Uses `x86_64` system images (requires manual edit)

If you're on x86_64, edit `Dockerfile.orchestrator` and replace `arm64-v8a` with `x86_64` in the system images installation step.

## Quick Start

### 1. Build the Orchestrator Image

```bash
./docker/build_orchestrator.sh
```

This creates the `mobilecybench-orchestrator:latest` image with all dependencies pre-installed.

### 2. Start the Orchestrator Container

```bash
./docker/start_orchestrator.sh
```

This starts the container with:
- Codebase mounted at `/mobilecybench`
- Docker daemon running inside the container
- KVM device mounted for hardware acceleration
- Results and logs persisted to host

### 3. Run Experiments

#### Option A: Using the helper script (recommended)

```bash
./docker/run_experiment.sh owncloud-android
```

#### Option B: Manually exec into container

```bash
# Exec into the running container
docker exec -it mobilecybench-orchestrator bash

# Inside the container:
./setup.sh owncloud-android      # Set up emulator for the app
./start_emulator.sh              # Start emulator
python3 runner.py owncloud-android runner_config.json
```

#### How App Backend Servers Are Started

When you run an experiment, the app's backend server cluster is automatically started using TRUE Docker-in-Docker:

1. **`./setup.sh <app_name>`** - Creates the Android emulator AVD
2. **`cd apps/<app_name> && ./setup.sh`** - This script:
   - Runs `docker compose up -d` which talks to the Docker daemon INSIDE the orchestrator container
   - Starts the app's backend containers (databases, app servers, etc.) INSIDE the orchestrator
   - The containers use the `shared_net` network defined in each app's `docker-compose.yml`
   - Waits for containers to be healthy
   - Seeds the database with initial data
   - Installs the APK on the emulator

**Important:** The orchestrator container runs its OWN Docker daemon. When the orchestrator runs `docker compose up`, it starts containers INSIDE itself. This means:
- App backend containers run INSIDE the orchestrator container (nested)
- The orchestrator has complete isolation from the host's Docker
- This is TRUE "Docker-in-Docker" (DinD)

**Visual Architecture:**
```
┌──────────────────────────────────────────────────────────┐
│ Your Computer (Host)                                     │
│                                                          │
│  ┌────────────────┐                                     │
│  │ Host Docker    │                                     │
│  │ Daemon         │                                     │
│  └────────┬───────┘                                     │
│           │                                             │
│           │ manages orchestrator only                   │
│           │                                             │
│  ┌────────▼─────────────────────────────────────────┐  │
│  │ orchestrator container                          │  │
│  │                                                 │  │
│  │  ┌──────────────────┐                          │  │
│  │  │ Docker Daemon    │                          │  │
│  │  │ (inside          │                          │  │
│  │  │  orchestrator)   │                          │  │
│  │  └────────┬─────────┘                          │  │
│  │           │                                     │  │
│  │           │ manages app containers              │  │
│  │           │                                     │  │
│  │  ┌────────▼────────────────────────────────┐   │  │
│  │  │                                         │   │  │
│  │  │  ┌─────────────┐  ┌──────────────┐    │   │  │
│  │  │  │ owncloud_   │  │ mariadb      │    │   │  │
│  │  │  │ server      │  │ container    │    │   │  │
│  │  │  │ container   │  │              │    │   │  │
│  │  │  └─────────────┘  └──────────────┘    │   │  │
│  │  │                                         │   │  │
│  │  │  ┌─────────────┐                       │   │  │
│  │  │  │ redis       │                       │   │  │
│  │  │  │ container   │                       │   │  │
│  │  │  └─────────────┘                       │   │  │
│  │  │                                         │   │  │
│  │  │  All connected via internal network    │   │  │
│  │  └─────────────────────────────────────────┘   │  │
│  │                                                 │  │
│  │  Android Emulator also runs here               │  │
│  │                                                 │  │
│  └─────────────────────────────────────────────────┘  │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

When you run `docker ps` on your HOST, you'll ONLY see the orchestrator container.
To see app backend containers, run `docker ps` INSIDE the orchestrator.

**Example workflow for ownCloud:**
```bash
# Inside orchestrator container
docker exec -it mobilecybench-orchestrator bash

# Set up emulator
./setup.sh owncloud-android

# Start emulator
./start_emulator.sh

# Setup app (this starts owncloud server, mariadb, redis containers INSIDE orchestrator)
cd apps/owncloud-android
./setup.sh
# → Runs: docker compose up -d (talks to Docker daemon inside orchestrator)
# → Starts: owncloud_server, mariadb, redis containers INSIDE orchestrator
# → These containers join the shared_net network inside orchestrator
# → Seeds database with test users and files
# → Installs APK on emulator

# Run experiment
cd /mobilecybench
python3 runner.py owncloud-android runner_config.json
```

**Verify app containers are running:**
```bash
# INSIDE orchestrator container
docker exec -it mobilecybench-orchestrator bash

# Then inside the orchestrator:
docker ps

# You should see:
# - owncloud_server
# - mariadb
# - redis
# (or similar, depending on the app)
# These are running INSIDE the orchestrator!

# On your HOST machine:
docker ps
# You'll ONLY see:
# - mobilecybench-orchestrator
```

### 4. Stop the Orchestrator

```bash
./docker/stop_orchestrator.sh
```

## Architecture

### Container Structure

```
mobilecybench-orchestrator
├── /mobilecybench/              # Mounted from host (read-write)
│   ├── apps/                    # App definitions
│   ├── agent/                   # Agent code
│   ├── runner.py               # Experiment runner
│   └── ...
├── /opt/android-sdk/            # Android SDK (baked into image)
│   ├── platform-tools/
│   ├── emulator/
│   └── platforms/
└── /usr/lib/jvm/java-17-openjdk-amd64/  # Java 17
```

### Volume Mounts

- **Codebase**: `./` → `/mobilecybench` (read-write)
  - All code changes on host are immediately reflected in container
- **Docker Data**: `orchestrator-docker-data` → `/var/lib/docker`
  - Persistent storage for Docker-in-Docker daemon
  - Stores images, containers, volumes created inside orchestrator
- **Results**: `./results` → `/mobilecybench/results`
- **Logs**: `./logs` → `/mobilecybench/logs`
- **Cgroups**: `/sys/fs/cgroup` → `/sys/fs/cgroup` (read-only)
  - Required for Docker-in-Docker to function properly

### Network Configuration

- **mobilecybench-net**: Bridge network connecting the orchestrator to the host
- App backend containers use their own networks INSIDE the orchestrator (managed by the inner Docker daemon)

## Running Experiments at Scale

### Parallel Execution

You can run multiple orchestrator containers in parallel for different experiments:

```bash
# Start multiple orchestrators with different names
docker-compose -f docker-compose.orchestrator.yml -p exp1 up -d
docker-compose -f docker-compose.orchestrator.yml -p exp2 up -d
docker-compose -f docker-compose.orchestrator.yml -p exp3 up -d

# Run different experiments in each
docker exec -it exp1-orchestrator-1 python3 runner.py owncloud-android
docker exec -it exp2-orchestrator-1 python3 runner.py conversations
docker exec -it exp3-orchestrator-1 python3 runner.py wordpress
```

### CI/CD Integration

The orchestrator is designed for CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Build Orchestrator
  run: ./docker/build_orchestrator.sh

- name: Run Experiment
  run: |
    ./docker/start_orchestrator.sh
    ./docker/run_experiment.sh ${{ matrix.app }}
```

## Environment Variables

Pass environment variables via `.env` file in project root:

```bash
# .env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
```

These are automatically loaded by `start_orchestrator.sh`.

## Troubleshooting

### Emulator won't start

**Issue**: Emulator fails with "KVM not found"

**Solution**:
```bash
# Check KVM access
ls -l /dev/kvm
# Should show: crw-rw---- 1 root kvm

# Add your user to kvm group
sudo usermod -aG kvm $USER
# Then logout and login again
```

### Container can't start app backends

**Issue**: "Cannot connect to Docker daemon"

**Solution**: Check if Docker daemon started inside orchestrator:
```bash
# Check orchestrator logs
docker logs mobilecybench-orchestrator | grep -i docker

# Exec into orchestrator and check Docker
docker exec mobilecybench-orchestrator docker info

# Check Docker daemon process
docker exec mobilecybench-orchestrator ps aux | grep dockerd
```

### Code changes not reflected

**Issue**: Changes to code don't appear in container

**Solution**: The codebase should be mounted, not copied. Verify with:
```bash
docker inspect mobilecybench-orchestrator | grep -A 10 Mounts
```

Should show:
```json
"Source": "/path/to/mobilecybench",
"Destination": "/mobilecybench",
"Mode": "rw"
```

### Slow emulator performance

**Issue**: Emulator is very slow

**Solutions**:
1. Ensure KVM is enabled (see above)
2. Increase CPU/memory limits in `docker-compose.orchestrator.yml`
3. Use x86_64 system images (not arm64) when possible

## Advanced Usage

### Custom SDK Versions

To add support for additional SDK versions, rebuild with:

```dockerfile
# Edit Dockerfile.orchestrator
RUN ${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager \
    "platforms;android-33" \
    "system-images;android-33;google_apis;x86_64"
```

Then rebuild:
```bash
./docker/build_orchestrator.sh
```

### Debugging

```bash
# View container logs
docker logs -f mobilecybench-orchestrator

# Check Docker daemon inside orchestrator
docker exec mobilecybench-orchestrator docker info
docker exec mobilecybench-orchestrator docker ps

# Check ADB devices
docker exec mobilecybench-orchestrator adb devices

# Check running emulators
docker exec mobilecybench-orchestrator ps aux | grep emulator

# View Docker daemon logs
docker exec mobilecybench-orchestrator tail -f /var/log/docker.log

# Interactive shell
docker exec -it mobilecybench-orchestrator bash
```

### Resource Limits

Adjust in `docker-compose.orchestrator.yml`:

```yaml
deploy:
  resources:
    limits:
      cpus: '8'        # More CPUs for parallel builds
      memory: 16G      # More memory for large apps
    reservations:
      cpus: '4'
      memory: 8G
```

## File Structure

```
mobilecybench/
├── Dockerfile.orchestrator           # Main orchestrator Dockerfile
├── docker-compose.orchestrator.yml   # Docker Compose configuration
└── docker/
    ├── README.md                     # This file
    ├── orchestrator-entrypoint.sh    # Container entrypoint script
    ├── build_orchestrator.sh         # Build helper
    ├── start_orchestrator.sh         # Start helper
    ├── stop_orchestrator.sh          # Stop helper
    └── run_experiment.sh             # Experiment runner helper
```

## Comparison with BountyBench

| Feature | BountyBench | MobileCybench Orchestrator |
|---------|-------------|----------------------------|
| Code Changes | Requires rebuild | Live mounted (no rebuild) |
| Android Emulator | Not supported | Full support with KVM |
| Multi-SDK | Single SDK | Multiple SDK versions |
| App Backends | External only | True Docker-in-Docker (nested) |
| Container Isolation | Partial | Complete (own Docker daemon) |
| Volume Mounts | Copy only | Mounted volumes |
| Development Speed | Slow (rebuild each time) | Fast (instant reflection) |

## Support

For issues or questions, please file an issue on the MobileCybench repository.
