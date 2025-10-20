# Docker Orchestrator Setup

## Container
### Build
```bash
docker compose -f docker-compose.orchestrator.yml build
```

### Start with Automatic Runner Execution
To run the orchestrator with automatic execution for a specific app:
```bash
# Set the app name and start the container
APP_NAME=conversations docker compose -f docker-compose.orchestrator.yml up -d

# View logs
docker compose -f docker-compose.orchestrator.yml logs -f
```

The container will automatically:
1. Start the Docker daemon
2. Create the `shared_net` network
3. Start the ADB server
4. Run `python3 runner.py <APP_NAME>`
5. The runner will automatically select the correct emulator based on the app's SDK version from `metadata.json`

### Start without Automatic Execution (Manual Mode)
If you want to manually control the container:
```bash
docker compose -f docker-compose.orchestrator.yml up -d
docker exec -it mobilecybench-orchestrator bash
```

## Building apps
### gradlew error
If you see an error like `./setup_app_source.sh: line 87: ./gradlew: cannot execute: required file not found`, this may be due to CRLF/LF Windows/Unix line endings conflict. This can be fixed with something like `dos2unix` (ex. `dos2unix apps/audiobookshelf/codebase/android/gradlew`).
