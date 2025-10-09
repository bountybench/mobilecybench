# MobileCybench Docker Environment

This directory contains the Docker setup for running MobileCybench experiments in a consistent, containerized environment.

## Key Features

- **Consistent Runtime Environment**: All dependencies (Android SDK, emulator, Python packages) pre-installed
- **Mounted Codebase**: Code is mounted, not copied - changes are reflected immediately without rebuilding
- **Android Emulator Support**: Run Android emulators inside Docker with KVM acceleration (x86_64)
- **Parallel Execution**: Run multiple experiments in parallel using separate containers
- **Docker-in-Docker**: Support for running nested containers when needed

## Architecture

The Docker setup consists of:

1. **Orchestrator Container** (`Dockerfile.orchestrator`): Main container with:
   - Python 3.12 runtime
   - Android SDK and emulator
   - All required tools and dependencies
   - KVM support for hardware acceleration

2. **Support Containers** (via docker-compose):
   - Kali container for security testing
   - MCP server for agent communication

## Quick Start

### Prerequisites

- Docker installed and running
- KVM support (for hardware acceleration on Linux)
- At least 8GB RAM available
- 20GB+ free disk space

### Building the Image

```bash
# Build the orchestrator image
./docker/build_orchestrator.sh

# Build without cache (force rebuild)
./docker/build_orchestrator.sh --no-cache

# Build for specific platform (x86_64 recommended)
./docker/build_orchestrator.sh --platform linux/amd64
```

### Running Experiments

```bash
# Run experiment for an app
./docker/run_experiment.sh conversations

# Use custom config
./docker/run_experiment.sh wordpress --config custom_config.json

# Run without KVM (slower emulator)
./docker/run_experiment.sh app_name --no-kvm

# Run interactively for debugging
./docker/run_experiment.sh app_name --interactive
```

### Using Docker Compose

```bash
cd docker

# Start all services
docker-compose up -d

# Run experiment inside orchestrator
docker-compose exec orchestrator python /mobilecybench/runner.py app_name

# View logs
docker-compose logs -f orchestrator

# Stop all services
docker-compose down
```

## Important Differences from BountyBench

1. **Code Mounting**: Unlike BountyBench which copies code into the image, we mount the codebase. This means:
   - No rebuild needed for code changes
   - Faster iteration during development
   - Results are written directly to host filesystem

2. **Android Emulator**: Full Android emulator support with:
   - KVM acceleration on Linux x86_64
   - Headless or GUI mode
   - Persistent AVD configuration

3. **Platform Considerations**:
   - **x86_64 (recommended)**: Full emulator support with KVM acceleration
   - **ARM64/Apple Silicon**: Limited support, emulator may be slow or unavailable

## Environment Variables

Create a `.env` file in the mobilecybench root directory:

```bash
OPENAI_API_KEY=your_api_key_here
HEADLESS_MODE=true  # Set to false for GUI debugging
SKIP_EMULATOR=false  # Set to true to skip emulator start
```

## Troubleshooting

### KVM Not Available

If you see "KVM is not available" warning:

**On Linux:**
```bash
# Check KVM support
ls -la /dev/kvm

# Enable KVM module
sudo modprobe kvm
sudo modprobe kvm_intel  # or kvm_amd

# Add user to kvm group
sudo usermod -aG kvm $USER
```

**On macOS:**
- KVM is not available on macOS
- Emulator will run without hardware acceleration (slower)
- Consider using x86_64 container on Linux for better performance

### Emulator Won't Start

1. Check available resources:
```bash
docker system df
docker stats
```

2. Increase Docker memory allocation (Docker Desktop settings)

3. Try without KVM:
```bash
./docker/run_experiment.sh app_name --no-kvm
```

### Permission Denied Errors

Make scripts executable:
```bash
chmod +x docker/*.sh
```

### Building on Apple Silicon

The Android emulator has limited ARM64 support. For Apple Silicon Macs:

1. Use x86_64 emulation (slower but more compatible):
```bash
./docker/build_orchestrator.sh --platform linux/amd64
```

2. Or run on an x86_64 Linux machine for best performance

## Advanced Usage

### Running Multiple Experiments

```bash
# Start orchestrator in background
docker run -d --name orchestrator1 --privileged \
  -v $(pwd):/mobilecybench \
  mobilecybench-orchestrator:latest

# Run experiments
docker exec orchestrator1 python /mobilecybench/runner.py app1
docker exec orchestrator1 python /mobilecybench/runner.py app2
```

### Debugging Inside Container

```bash
# Start interactive session
./docker/run_experiment.sh app_name --interactive

# Inside container:
# Check emulator status
adb devices

# View emulator logs
cat /var/log/emulator.log

# Test runner manually
python /mobilecybench/runner.py --help
```

### Custom Dockerfile

Create your own Dockerfile based on the orchestrator:

```dockerfile
FROM mobilecybench-orchestrator:latest

# Add custom tools or configurations
RUN apt-get update && apt-get install -y your-tools

# Override entrypoint if needed
ENTRYPOINT ["/your/custom/entrypoint.sh"]
```

## Resource Requirements

- **Minimum**: 4 CPU cores, 8GB RAM, 20GB disk
- **Recommended**: 8+ CPU cores, 16GB RAM, 50GB disk
- **KVM**: Required for hardware-accelerated emulator (Linux only)

## Security Notes

- Containers run in privileged mode for Docker-in-Docker and KVM support
- Mount Docker socket with caution in production environments
- Consider using separate Docker daemon for isolation

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review logs: `docker logs <container_name>`
3. File an issue with detailed error messages and environment info