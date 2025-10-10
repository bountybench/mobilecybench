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