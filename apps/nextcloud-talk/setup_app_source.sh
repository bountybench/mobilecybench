cd codebase

# Build the APK without installing
./gradlew packageGenericDebugUniversalApk || { echo "Gradle build failed"; exit 1; }

echo "Nextcloud Talk APK built successfully!"