# Docker Orchestrator Setup

## Container
### Build
```bash
docker compose -f docker-compose.orchestrator.yml build
```

### Start 
```bash
docker compose -f docker-compose.orchestrator.yml up -d
docker exec -it mobilecybench-orchestrator bash
```

### Inside the Orchestrator container, start the emulator in the background
```bash
emulator -avd MobileCybenchEmulatorAPI33 -no-window -no-audio -no-snapshot-save -wipe-data -gpu off -skin 1080x1920 -memory 2048 &
# or
emulator -avd MobileCybenchEmulatorAPI34 -no-window -no-audio -no-snapshot-save -wipe-data -gpu off -skin 1080x1920 -memory 2048 &
# or
emulator -avd MobileCybenchEmulatorAPI35 -no-window -no-audio -no-snapshot-save -wipe-data -gpu off -skin 1080x1920 -memory 2048 &
# note: Bitwarden is on SDK 33; others are on 34 and 35.
```

## Building apps
### gradlew error
If you see an error like `./setup_app_source.sh: line 87: ./gradlew: cannot execute: required file not found`, this may be due to CRLF/LF Windows/Unix line endings conflict. This can be fixed with something like `dos2unix` (ex. `dos2unix apps/audiobookshelf/codebase/android/gradlew`).