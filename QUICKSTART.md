# MobileCybench Quick Start Guide

## Automated Experiment Running

The easiest way to run experiments is using the automated script:

```bash
./docker/run_experiment.sh <app_name> [config_file] [--keep-running]
```

### Examples

```bash
# Run experiment for audiobookshelf (uses default config)
./docker/run_experiment.sh audiobookshelf

# Run with custom config
./docker/run_experiment.sh owncloud-android custom_config.json

# Keep container running after experiment completes
./docker/run_experiment.sh audiobookshelf --keep-running
```

### What the Script Does

The automated script handles everything for you:

1. **Builds** the backend container (if not already built)
2. **Starts** the container with Docker-in-Docker
3. **Waits** for Docker daemon to be ready inside
4. **Sets up** the emulator and app environment
5. **Runs** the experiment
6. **Shows** live output as it runs
7. **Cleans up** when done (stops container unless --keep-running)

### Output

Results and logs are saved to:
- `./results/` - Experiment results
- `./logs/` - Detailed logs

### Troubleshooting

If the container is already running from a previous experiment:
```bash
# Stop existing container first
docker compose down

# Then run your experiment
./docker/run_experiment.sh audiobookshelf
```

Check container logs if something goes wrong:
```bash
docker logs mobilecybench-backend
```

View child containers running inside:
```bash
docker exec mobilecybench-backend docker ps
```

## Manual Control (Advanced)

If you need more control over the process:

```bash
# 1. Build and start backend
docker compose build backend
docker compose up -d backend

# 2. Exec into container
docker exec -it mobilecybench-backend bash

# 3. Inside container: set up and run
cd /mobilecybench
./setup.sh <app_name>
./start_emulator.sh --yes
python3 runner.py <app_name>

# 4. Exit and stop container
exit
docker compose down
```

## Architecture

MobileCybench uses Docker-in-Docker (DinD):

```
Host Machine
└── mobilecybench-backend (privileged container)
    ├── Docker Daemon (running inside)
    ├── Android Emulator
    └── Child Containers
        ├── kali-agent-1
        ├── app-database
        └── app-server
```

All child containers (agents, app backends) spawn inside the backend container, providing complete isolation from the host.

## First Time Setup

### Prerequisites

- Docker and Docker Compose
- At least 8GB RAM
- At least 20GB disk space
- For Linux: KVM support for hardware acceleration

### Create Required Volume

```bash
docker volume create dind-data
docker volume create gradle-cache
```

### Configure API Keys (Optional)

Create a `.env` file in the project root:

```bash
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=...
```

### Run Your First Experiment

```bash
./docker/run_experiment.sh audiobookshelf
```

That's it! The script handles everything else automatically.
