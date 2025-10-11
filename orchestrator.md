# Docker Orchestrator Setup

In `docker-compose.dind.yml`, uncomment the lines in `environment` if using host ADB server is desired.

## Starting Container
### Build
```bash
docker compose -f docker-compose.dind.yml build
```

### Start 
```bash
docker compose -f docker-compose.dind.yml up -d
docker exec -it mobilecybench-orchestrator bash
```

## Install tools
### Install image
```bash
sdkmanager "system-images;android-35;google_apis;x86_64"
```

### Start ADB Server
```bash
adb start-server
```

### Create avd
```bash
avdmanager create avd -n test_x86 \
  -k "system-images;android-35;google_apis;x86_64" \
  --device "pixel_6"
```

### Run emulator
```bash
/opt/android-sdk/emulator/emulator -avd test_x86 -no-window -gpu off
```

## Building apps
### gradlew error
If you see an error like `./setup_app_source.sh: line 87: ./gradlew: cannot execute: required file not found`, this may be due to CRLF/LF Windows/Unix line endings conflict. This can be fixed with something like `dos2unix` (ex. `dos2unix apps/audiobookshelf/codebase/android/gradlew`).