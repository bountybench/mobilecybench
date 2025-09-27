
#!/bin/bash
set -e

# Ensure correct Java version
if ! java -version 2>&1 | grep "17"; then
    echo "Java 17 not found, installing..."
    sudo apt-get update
    sudo apt-get install -y openjdk-17-jdk
fi

cd codebase 
# Continue with Gradle build
./gradlew  assembleRelease

