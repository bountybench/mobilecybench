# FairEmail 

This repository contains the setup and build scripts for integrating FairEmail 

## About FairEmail

FairEmail is a privacy-friendly, open source email app for Android. It features:

- **Privacy First**: No ads, no tracking, no analytics, no data collection
- **Open Source**: Full source code available under GPL-3.0 license
- **Secure**: Supports PGP encryption and S/MIME
- **Feature Rich**: Unified inbox, conversation view, search, offline support
- **Customizable**: Dark theme, widgets, multiple accounts, folder management

## Quick Start

### Prerequisites

- **Java 8 or higher** - Required for building
- **Android SDK** - Required for building and testing
- **Android Emulator** - For testing the app
- **Git** - For managing the repository

### Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd BAIR-APPS
   ```

2. **Initialize submodules:**
   ```bash
   git submodule update --init --recursive
   ```

3. **Run the setup script:**
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```

The setup script will:
- Check for required dependencies
- Build FairEmail from source
- Install the APK on your Android emulator
- Launch the app

## Manual Setup

If you prefer to run the steps manually:

### 1. Build from Source

```bash
chmod +x setup_app_source.sh
./setup_app_source.sh
```

This script will:
- Check Java and Android SDK availability
- Clean previous builds
- Build the FairEmail APK
- Display build information

### 2. Install on Emulator

```bash
# Start your Android emulator first
emulator -avd <your_avd_name>

# Install the APK
adb install -r FairEmail/app/build/outputs/apk/play/release/FairEmail-v1.2300a-play-release.apk

# Launch the app
adb shell am start -n eu.faircode.email/.ui.ActivityMain
```

## Project Structure

```
BAIR-APPS/
├── setup.sh                 # Main entrypoint script
├── setup_app_source.sh      # Build from source script
├── metadata.json            # App metadata and configuration
├── README.md               # This file
└── FairEmail/              # FairEmail submodule
    ├── app/                # Main application module
    ├── colorpicker/        # Color picker library
    ├── openpgp-api/        # OpenPGP API library
    └── ...
```

## Configuration

### Android SDK Setup

Make sure your Android SDK is properly configured:

```bash
export ANDROID_HOME=/path/to/your/android/sdk
export ANDROID_SDK_ROOT=$ANDROID_HOME
export PATH=$PATH:$ANDROID_HOME/tools:$ANDROID_HOME/platform-tools
```

### Build Variants

FairEmail supports multiple build variants:

- **play** - Play Store version (default)
- **github** - GitHub release version
- **fdroid** - F-Droid version
- **large** - Large heap version
- **amazon** - Amazon Appstore version

### Signing Configuration

For release builds, create a `keystore.properties` file in the FairEmail directory:

```properties
storeFile=path/to/your/keystore.jks
storePassword=your_store_password
keyAlias=your_key_alias
keyPassword=your_key_password
```

If no keystore is provided, the build will use debug signing.

## Development

### Building Specific Variants

```bash
cd FairEmail
./gradlew :app:assemblePlayRelease    # Play Store variant
./gradlew :app:assembleGithubRelease  # GitHub variant
./gradlew :app:assembleFdroidRelease  # F-Droid variant
```

### Running Tests

```bash
cd FairEmail
./gradlew test
./gradlew connectedAndroidTest
```

### Code Style

The project follows Android's standard code style guidelines. Use the provided lint configuration for consistency.

## Troubleshooting

### Common Issues

1. **"ADB not found"**
   - Install Android SDK and add platform-tools to PATH
   - Verify with `adb version`

2. **"Java not found"**
   - Install Java 8 or higher
   - Set JAVA_HOME environment variable

3. **"Android SDK not found"**
   - Set ANDROID_HOME or ANDROID_SDK_ROOT
   - Verify SDK installation

4. **"No emulator detected"**
   - Start an Android emulator
   - Verify with `adb devices`

5. **Build failures**
   - Clean build: `./gradlew clean`
   - Check Java and Android SDK versions
   - Ensure sufficient disk space

### Build Errors

- **Signing errors**: Create keystore.properties or use debug signing
- **Memory errors**: Increase Gradle heap size in gradle.properties
- **Dependency errors**: Check internet connection and repository access

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

FairEmail is licensed under the GPL-3.0 License. See the [LICENSE](FairEmail/LICENSE) file for details.

## Links

- [FairEmail Homepage](https://email.faircode.eu/)
- [GitHub Repository](https://github.com/M66B/FairEmail)
- [Documentation](https://github.com/M66B/FairEmail/blob/master/README.md)
- [Privacy Policy](https://email.faircode.eu/privacy/)
- [Donate](https://email.faircode.eu/donate/)

## Support

For issues related to:
- **FairEmail itself**: [GitHub Issues](https://github.com/M66B/FairEmail/issues)
- **This integration**: Create an issue in this repository
- **General questions**: [FairEmail FAQ](https://github.com/M66B/FairEmail/blob/master/FAQ.md)
