# ARM64 (Apple Silicon) Setup Guide for MobileCybench

## Overview

MobileCybench now supports ARM64 architecture (Apple Silicon Macs), but with some important limitations and considerations due to the Android emulator not being available for ARM64 Linux.

## Key Limitations on ARM64

1. **No Android Emulator for ARM64 Linux**: Google does not provide Android emulator binaries for ARM64 Linux
2. **Alternative Solutions Required**: You must use either:
   - Host Android emulator with bridge (recommended)
   - Physical Android device connected via ADB
   - QEMU emulation (slower)

## What Has Been Fixed

✅ **ADB Bridge Shim**: Installed as `/usr/local/bin/adb` for host communication
✅ **Dynamic JAVA_HOME**: Automatically detects correct Java path for architecture
✅ **Conditional SDK Installation**: Only installs emulator on x86_64
✅ **QEMU Support**: Added for cross-architecture emulation if needed

## Quick Start

### 1. Build and Start the Orchestrator

```bash
# Build with ARM64 support
docker compose build orchestrator

# Start the container
docker compose up -d orchestrator
```

### 2. Verify ARM64 Setup

```bash
# Check architecture and tools
docker exec mobilecybench-orchestrator bash -c "uname -m && which adb && echo \$JAVA_HOME"
```

Expected output:
```
aarch64
/usr/local/bin/adb
/usr/lib/jvm/java-17-openjdk
```

### 3. Install SDK Components

```bash
docker exec mobilecybench-orchestrator bash -c "
  export JAVA_HOME=/usr/lib/jvm/java-17-openjdk
  export ANDROID_HOME=/root/.android-sdk
  export PATH=\$PATH:\$ANDROID_HOME/cmdline-tools/latest/bin

  # Install SDK packages (emulator not available for ARM64)
  sdkmanager 'platform-tools' 'platforms;android-35' 'build-tools;34.0.0'
"
```

## Running Experiments on ARM64

### Option 1: Host Emulator with Bridge (Recommended)

1. **On the host (macOS)**, install and start Android emulator:
   ```bash
   # Install Android Studio or command line tools
   # Create and start an AVD
   emulator -avd your_avd_name
   ```

2. **Start the bridge** on the host (port 52888):
   ```bash
   # This allows the container to communicate with host emulator
   ./start_bridge.sh  # You need to implement this
   ```

3. **In the container**, run experiments:
   ```bash
   docker exec -it mobilecybench-orchestrator bash
   cd /mobilecybench
   python3 runner.py audiobookshelf
   ```

### Option 2: Physical Device

1. **Connect Android device** to host via USB
2. **Enable USB debugging** on the device
3. **Forward ADB** from host to container:
   ```bash
   # On host
   adb kill-server
   adb -a nodaemon server start
   ```

4. **In container**, connect to host ADB:
   ```bash
   export ADB_SERVER_HOST=host.docker.internal
   adb devices  # Should show your device
   ```

### Option 3: QEMU Emulation (Slow)

Use QEMU to emulate x86_64 Android on ARM64:
```bash
# In container
qemu-system-x86_64 -enable-kvm ...  # Complex setup, not recommended
```

## Troubleshooting

### Error: "Failed to find package 'emulator'"
**Expected on ARM64** - The emulator package isn't available for ARM64 Linux. Use host emulator or physical device.

### Error: "JAVA_HOME is set to an invalid directory"
**Solution**: Ensure JAVA_HOME points to `/usr/lib/jvm/java-17-openjdk` (not the amd64-specific path)

### Error: "adb shim missing"
**Solution**: Rebuild the orchestrator container - the bridge_shim.py should be installed as `/usr/local/bin/adb`

### Error: "qemu-x86_64: Could not open '/lib64/ld-linux-x86-64.so.2'"
**Cause**: Trying to run x86_64 binaries on ARM64
**Solution**: Use the host emulator or ARM64-compatible approaches

## Architecture Detection

The system automatically detects architecture:
- **x86_64 (amd64)**: Full emulator support
- **ARM64 (aarch64)**: Limited to bridge/device approaches

## Development Workflow

1. **Code changes** are immediately reflected (volume mounted)
2. **SDK tools** work normally (except emulator)
3. **Building apps** works the same
4. **Testing** requires alternative emulator approach

## Future Improvements

- [ ] Automated bridge setup for host emulator
- [ ] Better ARM64 emulator detection
- [ ] Native ARM64 Android emulator when available
- [ ] Rosetta 2 integration for macOS

## References

- [Android Emulator on Apple Silicon](https://developer.android.com/studio/run/emulator-apple-silicon)
- [Docker Desktop for Mac](https://docs.docker.com/desktop/mac/apple-silicon/)
- [QEMU Documentation](https://www.qemu.org/documentation/)